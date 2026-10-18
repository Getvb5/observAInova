from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx

from pci.claims.contracts import ExtractionDocument, ProviderExtraction

TRANSIENT_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class ProviderError(RuntimeError):
    pass


class DeterministicExtractionProvider:
    def __init__(
        self,
        fixtures: Mapping[str, ProviderExtraction],
        *,
        provider_name: str = "deterministic",
        model_name: str = "fixture-v1",
        schema_version: str = "v1",
        instruction_version: str = "v1",
    ) -> None:
        self._fixtures = dict(fixtures)
        first = next(iter(self._fixtures.values()), None)
        self.provider_name = first.provider if first is not None else provider_name
        self.model_name = first.model if first is not None else model_name
        self.schema_version = first.schema_version if first is not None else schema_version
        self.instruction_version = (
            first.instruction_version if first is not None else instruction_version
        )

    def extract(self, document: ExtractionDocument) -> ProviderExtraction:
        extraction = self._fixtures.get(document.checksum)
        if extraction is None:
            raise ProviderError("fixture_not_found")
        return extraction.model_copy(deep=True)


class HttpExtractionProvider:
    provider_name = "http"

    def __init__(
        self,
        endpoint_url: str,
        api_key: str,
        model: str,
        timeout: float,
        *,
        schema_version: str = "v1",
        instruction_version: str = "v1",
        allow_insecure: bool = False,
        max_retries: int = 2,
        http: httpx.Client | None = None,
    ) -> None:
        parsed = urlsplit(endpoint_url)
        if parsed.scheme != "https" and not allow_insecure:
            raise ValueError("extraction endpoint must use HTTPS")
        if max_retries < 0 or max_retries > 2:
            raise ValueError("max_retries must be between zero and two")
        self.endpoint_url = endpoint_url
        self.api_key = api_key
        self.model_name = model
        self.schema_version = schema_version
        self.instruction_version = instruction_version
        self.timeout = timeout
        self.max_retries = max_retries
        self._http = http

    def extract(self, document: ExtractionDocument) -> ProviderExtraction:
        client = self._http or httpx.Client(timeout=self.timeout, trust_env=False)
        owns_client = self._http is None
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    response = client.post(
                        self.endpoint_url,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "model": self.model_name,
                            "schema_version": self.schema_version,
                            "instruction_version": self.instruction_version,
                            "document": document.model_dump(mode="json"),
                        },
                    )
                except httpx.TransportError as exc:
                    if attempt == self.max_retries:
                        raise ProviderError("provider_transport_error") from exc
                    continue
                if response.status_code in TRANSIENT_STATUSES and attempt < self.max_retries:
                    continue
                if response.status_code >= 400:
                    raise ProviderError(f"provider_http_{response.status_code}")
                try:
                    return ProviderExtraction.model_validate(response.json())
                except (ValueError, TypeError) as exc:
                    raise ProviderError("provider_response_invalid") from exc
            raise ProviderError("provider_retry_exhausted")
        finally:
            if owns_client:
                client.close()
