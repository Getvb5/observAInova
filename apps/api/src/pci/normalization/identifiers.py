import re
from collections.abc import Iterable
from urllib.parse import quote, urlsplit, urlunsplit

from pci.normalization.text import normalize_display

DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
ORCID_PATTERN = re.compile(r"\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?[\dX]{4}", re.IGNORECASE)
ISBN_PATTERN = re.compile(r"(?:97[89])?\d{9}[\dX]", re.IGNORECASE)
BARE_HANDLE_PATTERN = re.compile(r"\d+(?:\.\d+)*/[^\s/]+")


def normalize_doi(value: str) -> str | None:
    cleaned = normalize_display(value)
    cleaned = re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    match = DOI_PATTERN.fullmatch(cleaned)
    return cleaned.rstrip(". ,;").casefold() if match else None


def normalize_orcid(value: str) -> str | None:
    cleaned = normalize_display(value)
    cleaned = re.sub(r"^(?:https?://orcid\.org/|orcid:\s*)", "", cleaned, flags=re.IGNORECASE)
    compact = re.sub(r"[- ]", "", cleaned).upper()
    if not re.fullmatch(r"\d{15}[\dX]", compact):
        return None
    return "-".join(compact[index : index + 4] for index in range(0, 16, 4))


def normalize_isbn(value: str) -> str | None:
    cleaned = re.sub(
        r"^isbn(?:-1[03])?:?\s*",
        "",
        normalize_display(value),
        flags=re.IGNORECASE,
    )
    compact = re.sub(r"[^\dXx]", "", cleaned).upper()
    return compact if ISBN_PATTERN.fullmatch(compact) else None


def normalize_patent(value: str) -> str | None:
    compact = re.sub(r"[^0-9A-Za-z]", "", normalize_display(value)).upper()
    return compact or None


def normalize_handle(value: str) -> str | None:
    cleaned = normalize_display(value)
    prefixed = re.match(
        r"^(?:https?://hdl\.handle\.net/|hdl:\s*|handle:\s*)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if prefixed is not None:
        cleaned = cleaned[prefixed.end() :]
    elif BARE_HANDLE_PATTERN.fullmatch(cleaned) is None:
        return None
    if "/" not in cleaned or any(char.isspace() for char in cleaned):
        return None
    return cleaned.strip("/").casefold() or None


def normalize_url(value: str) -> str | None:
    cleaned = normalize_display(value)
    try:
        parts = urlsplit(cleaned)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        return None
    scheme = parts.scheme.casefold()
    host = parts.hostname.casefold()
    if ":" in host:
        host = f"[{host}]"
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
    if path != "/":
        path = path.rstrip("/")
    query = quote(parts.query, safe="=&;%:+,/?@!$'()*-._~")
    return urlunsplit((scheme, host, path, query, ""))


def classify_identifier(value: str) -> tuple[str, str] | None:
    for key, normalizer in (
        ("doi", normalize_doi),
        ("orcid", normalize_orcid),
        ("isbn", normalize_isbn),
        ("handle", normalize_handle),
    ):
        if normalized := normalizer(value):
            return key, normalized
    if normalized_url := normalize_url(value):
        return "url", normalized_url
    return None


def string_values(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                yield item
