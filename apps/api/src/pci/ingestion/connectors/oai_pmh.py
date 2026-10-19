import asyncio
from collections.abc import AsyncIterator
from typing import Any
from xml.etree import ElementTree

import httpx

from pci.ingestion.contracts import HarvestedRecord

OAI_NAMESPACE = "http://www.openarchives.org/OAI/2.0/"
OAI = f"{{{OAI_NAMESPACE}}}"
TRANSIENT_STATUSES = frozenset({403, 408, 429, 500, 502, 503, 504})
DEFAULT_USER_AGENT = "ObservAInova/0.1 (scientific metadata harvester)"


class OaiPmhConnector:
    def __init__(
        self,
        base_url: str,
        *,
        metadata_prefix: str = "oai_dc",
        set_spec: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        request_interval_seconds: float = 0.0,
        retry_base_delay_seconds: float = 0.0,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds cannot be negative")
        if retry_base_delay_seconds < 0:
            raise ValueError("retry_base_delay_seconds cannot be negative")
        self.base_url = base_url
        self.metadata_prefix = metadata_prefix
        self.set_spec = set_spec
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_interval_seconds = request_interval_seconds
        self.retry_base_delay_seconds = retry_base_delay_seconds

    async def harvest(self, cursor: str | None) -> AsyncIterator[HarvestedRecord]:
        token = cursor
        async with httpx.AsyncClient(
            timeout=self.timeout,
            trust_env=False,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        ) as client:
            while True:
                params = {"verb": "ListRecords"}
                if token is None:
                    params["metadataPrefix"] = self.metadata_prefix
                    if self.set_spec:
                        params["set"] = self.set_spec
                else:
                    params["resumptionToken"] = token

                response = await self._request_with_retry(client, params)
                root = ElementTree.fromstring(response.content)
                self._raise_oai_error(root)
                for element in root.findall(f".//{OAI}ListRecords/{OAI}record"):
                    yield self._parse_record(element)

                token_element = root.find(f".//{OAI}ListRecords/{OAI}resumptionToken")
                token = _text(token_element)
                if token is None:
                    return
                await asyncio.sleep(self.request_interval_seconds)

    async def _request_with_retry(
        self, client: httpx.AsyncClient, params: dict[str, str]
    ) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(self.base_url, params=params)
            except httpx.TransportError:
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(self.retry_base_delay_seconds * (2**attempt))
                continue

            if response.status_code in TRANSIENT_STATUSES and attempt < self.max_retries:
                await asyncio.sleep(_retry_delay(response, self.retry_base_delay_seconds, attempt))
                continue
            response.raise_for_status()
            return response

        raise RuntimeError("unreachable retry state")

    @staticmethod
    def _raise_oai_error(root: ElementTree.Element) -> None:
        error = root.find(f"{OAI}error")
        if error is not None:
            code = error.attrib.get("code", "unknown")
            raise RuntimeError(f"OAI-PMH error {code}: {_text(error) or ''}".rstrip())

    @staticmethod
    def _parse_record(element: ElementTree.Element) -> HarvestedRecord:
        identifier = _text(element.find(f"{OAI}header/{OAI}identifier"))
        if identifier is None:
            raise ValueError("OAI-PMH record is missing its header identifier")

        metadata = element.find(f"{OAI}metadata")
        dc_values: dict[str, list[str]] = {}
        if metadata is not None:
            for child in metadata.iter():
                if child is metadata or len(child):
                    continue
                value = _text(child)
                if value is None:
                    continue
                name = child.tag.rsplit("}", 1)[-1]
                dc_values.setdefault(name, []).append(value)

        payload: dict[str, Any] = {
            name: values[0] if len(values) == 1 else values
            for name, values in dc_values.items()
        }
        _set_alias(payload, "abstract", dc_values.get("description"))
        if creators := dc_values.get("creator"):
            payload["authors"] = creators
        if identifiers := dc_values.get("identifier"):
            payload["identifiers"] = identifiers
        payload["_oai_pmh"] = _element_payload(element)

        source_url = next(
            (
                value
                for value in dc_values.get("identifier", [])
                if value.startswith(("http://", "https://"))
            ),
            None,
        )
        rights_values = dc_values.get("rights", [])
        rights = rights_values[0] if rights_values else None
        header = element.find(f"{OAI}header")
        return HarvestedRecord(
            identifier,
            payload,
            source_url,
            rights,
            is_tombstone=header is not None and header.attrib.get("status") == "deleted",
        )


def _set_alias(payload: dict[str, Any], name: str, values: list[str] | None) -> None:
    if values:
        payload[name] = values[0] if len(values) == 1 else values


def _retry_delay(response: httpx.Response, base_delay: float, attempt: int) -> float:
    raw_retry_after = response.headers.get("Retry-After")
    if raw_retry_after is not None:
        try:
            return max(float(str(raw_retry_after)), 0.0)
        except ValueError:
            pass
    return base_delay * float(2**attempt)


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _element_payload(
    element: ElementTree.Element, *, include_tail: bool = False
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tag": element.tag,
        "attributes": dict(element.attrib),
        "text": element.text,
        "children": [_element_payload(child, include_tail=True) for child in element],
    }
    if include_tail and element.tail is not None:
        payload["tail"] = element.tail
    return payload
