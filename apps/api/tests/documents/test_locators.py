import httpx
import pytest

from pci.documents.locators import (
    DocumentAcquisitionError,
    DspaceDocumentLocator,
    document_allowed_hosts,
    download_pdf,
)
from pci.models.enums import RightsPolicy
from pci.models.provenance import RawRecord, Source


def raw_record(
    *,
    payload: dict[str, object] | None = None,
    source_url: str = "https://repositorio.example/items/42",
) -> RawRecord:
    source = Source(
        code="fixture",
        name="Repositório",
        connector_type="oai_pmh",
        base_url="https://repositorio.example/oai/request",
        rights_policy=RightsPolicy.OPEN_COPY,
        schedule={},
    )
    return RawRecord(
        source=source,
        source_identifier="oai:fixture:42",
        payload=payload or {},
        source_url=source_url,
        checksum="checksum",
    )


def client_for(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, follow_redirects=False)


def test_locator_prefers_a_direct_same_origin_pdf_identifier() -> None:
    transport = httpx.MockTransport(lambda _: pytest.fail("landing page was requested"))
    locator = DspaceDocumentLocator(http=client_for(transport))
    raw = raw_record(
        payload={
            "identifiers": [
                "https://repositorio.example/items/42",
                "https://repositorio.example/bitstream/123/1/tese.pdf",
            ]
        }
    )

    location = locator.locate(raw)

    assert location is not None
    assert location.url == "https://repositorio.example/bitstream/123/1/tese.pdf"
    assert location.media_type == "application/pdf"


def test_locator_rejects_cross_origin_and_non_pdf_links() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                '<a href="https://evil.example/file.pdf">PDF</a>'
                '<a href="/bitstream/123/1/readme.txt">texto</a>'
            ),
            headers={"content-type": "text/html"},
        )

    locator = DspaceDocumentLocator(http=client_for(httpx.MockTransport(handler)))

    assert locator.locate(raw_record()) is None


def test_download_revalidates_cross_origin_redirect() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/tese.pdf"})

    with pytest.raises(DocumentAcquisitionError, match="untrusted_host"):
        download_pdf(
            "https://repositorio.example/tese.pdf",
            allowed_hosts=frozenset({"repositorio.example"}),
            http=client_for(httpx.MockTransport(handler)),
        )


def test_download_rejects_oversize_wrong_type_and_pdf_magic_mismatch() -> None:
    responses = (
        httpx.Response(
            200, content=b"%PDF-" + b"x" * 20, headers={"content-type": "application/pdf"}
        ),
        httpx.Response(200, content=b"plain text", headers={"content-type": "text/plain"}),
    )
    for response in responses:
        client = client_for(httpx.MockTransport(lambda _, item=response: item))
        with pytest.raises(DocumentAcquisitionError):
            download_pdf(
                "https://repositorio.example/tese.pdf",
                allowed_hosts=frozenset({"repositorio.example"}),
                max_bytes=10,
                http=client,
            )


def test_record_url_cannot_authorize_its_own_download_host() -> None:
    raw = raw_record(source_url="https://attacker.example/items/42")

    assert "attacker.example" not in document_allowed_hosts(raw)
    assert document_allowed_hosts(raw) == frozenset({"repositorio.example"})


def test_pdf_header_without_pdf_magic_is_rejected() -> None:
    client = client_for(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=b"not-pdf", headers={"content-type": "application/pdf"}
            )
        )
    )
    with pytest.raises(DocumentAcquisitionError, match="not_a_pdf"):
        download_pdf(
            "https://repositorio.example/tese.pdf",
            allowed_hosts=frozenset({"repositorio.example"}),
            http=client,
        )
