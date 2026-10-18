import ipaddress
import socket
from collections.abc import Iterable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from pci.documents.contracts import DocumentLocation, DownloadedDocument
from pci.models.provenance import RawRecord

TRANSIENT_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
MAX_REDIRECTS = 5
MAX_LANDING_BYTES = 1_048_576


class DocumentAcquisitionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code[:100]
        super().__init__(self.code)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        for key, value in attrs:
            if key.casefold() == "href" and value:
                self.links.append(value)


class DspaceDocumentLocator:
    def __init__(self, *, timeout: float = 30.0, http: httpx.Client | None = None) -> None:
        self._enforce_public_network = http is None
        self._http = http or httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)

    def locate(self, raw: RawRecord) -> DocumentLocation | None:
        allowed_hosts = document_allowed_hosts(raw)
        for candidate in _identifier_urls(raw):
            if _is_permitted_url(candidate, allowed_hosts) and _looks_like_pdf(candidate):
                return DocumentLocation(candidate, "application/pdf", raw.rights_snapshot)
        if raw.source_url is None or not _is_permitted_url(raw.source_url, allowed_hosts):
            return None
        try:
            landing_url, html = _download_landing(
                raw.source_url,
                allowed_hosts=allowed_hosts,
                http=self._http,
                enforce_public_network=self._enforce_public_network,
            )
        except DocumentAcquisitionError:
            return None
        parser = _LinkParser()
        parser.feed(html)
        for href in parser.links:
            candidate = urljoin(landing_url, href)
            if _is_permitted_url(candidate, allowed_hosts) and _looks_like_pdf(candidate):
                return DocumentLocation(candidate, "application/pdf", raw.rights_snapshot)
        return None


def document_allowed_hosts(raw: RawRecord) -> frozenset[str]:
    hosts: set[str] = set()
    host = urlsplit(raw.source.base_url).hostname if raw.source.base_url else None
    if host:
        hosts.add(host.casefold())
    schedule = raw.source.schedule or {}
    configured = schedule.get("document_host_allowlist", [])
    if isinstance(configured, list):
        hosts.update(item.casefold() for item in configured if isinstance(item, str) and item)
    return frozenset(hosts)


def download_pdf(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    max_bytes: int = 100 * 1024 * 1024,
    timeout: float = 30.0,
    max_retries: int = 2,
    http: httpx.Client | None = None,
) -> DownloadedDocument:
    if max_bytes < 1 or max_bytes > 100 * 1024 * 1024:
        raise DocumentAcquisitionError("invalid_size_limit")
    if max_retries < 0 or max_retries > 2:
        raise DocumentAcquisitionError("invalid_retry_limit")
    client = http or httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)
    owns_client = http is None
    try:
        for attempt in range(max_retries + 1):
            try:
                return _download_pdf_once(
                    url,
                    allowed_hosts=allowed_hosts,
                    max_bytes=max_bytes,
                    http=client,
                    enforce_public_network=owns_client,
                )
            except httpx.TransportError as exc:
                if attempt == max_retries:
                    raise DocumentAcquisitionError("transport_error") from exc
            except DocumentAcquisitionError as exc:
                if exc.code != "transient_http_error" or attempt == max_retries:
                    raise
        raise DocumentAcquisitionError("transport_error")
    finally:
        if owns_client:
            client.close()


def _download_pdf_once(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    max_bytes: int,
    http: httpx.Client,
    enforce_public_network: bool,
) -> DownloadedDocument:
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        _require_permitted_url(
            current_url, allowed_hosts, enforce_public_network=enforce_public_network
        )
        with http.stream("GET", current_url) as response:
            if response.status_code in TRANSIENT_STATUSES:
                raise DocumentAcquisitionError("transient_http_error")
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise DocumentAcquisitionError("redirect_without_location")
                current_url = urljoin(str(response.url), location)
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise DocumentAcquisitionError("http_error") from exc
            declared_length = response.headers.get("content-length")
            if declared_length is not None:
                try:
                    if int(declared_length) > max_bytes:
                        raise DocumentAcquisitionError("document_too_large")
                except ValueError:
                    pass
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise DocumentAcquisitionError("document_too_large")
            data = bytes(content)
            if not data.startswith(b"%PDF-"):
                raise DocumentAcquisitionError("not_a_pdf")
            return DownloadedDocument(
                content=data,
                media_type="application/pdf",
                final_url=current_url,
            )
    raise DocumentAcquisitionError("too_many_redirects")


def _download_landing(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    http: httpx.Client,
    enforce_public_network: bool,
) -> tuple[str, str]:
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        _require_permitted_url(
            current_url, allowed_hosts, enforce_public_network=enforce_public_network
        )
        response = http.get(current_url, follow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise DocumentAcquisitionError("redirect_without_location")
            current_url = urljoin(str(response.url), location)
            continue
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DocumentAcquisitionError("landing_http_error") from exc
        if len(response.content) > MAX_LANDING_BYTES:
            raise DocumentAcquisitionError("landing_too_large")
        return current_url, response.text
    raise DocumentAcquisitionError("too_many_redirects")


def _identifier_urls(raw: RawRecord) -> Iterable[str]:
    for field in ("identifiers", "identifier", "url"):
        value = raw.payload.get(field)
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            yield from (item for item in value if isinstance(item, str))


def _looks_like_pdf(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    filename = path.rsplit("/", 1)[-1]
    return path.endswith(".pdf") or ("/bitstream/" in path and "." not in filename)


def _is_permitted_url(url: str, allowed_hosts: frozenset[str]) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme.casefold() == "https"
        and parsed.hostname is not None
        and parsed.hostname.casefold() in allowed_hosts
        and parsed.username is None
        and parsed.password is None
    )


def _require_permitted_url(
    url: str,
    allowed_hosts: frozenset[str],
    *,
    enforce_public_network: bool = False,
) -> None:
    if not _is_permitted_url(url, allowed_hosts):
        raise DocumentAcquisitionError("untrusted_host")
    if enforce_public_network:
        host = urlsplit(url).hostname
        assert host is not None
        try:
            addresses = {
                item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise DocumentAcquisitionError("host_resolution_failed") from exc
        if not addresses or any(not ipaddress.ip_address(item).is_global for item in addresses):
            raise DocumentAcquisitionError("non_public_address")
