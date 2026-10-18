import uuid

import pytest
from sqlalchemy.orm import Session

from pci.documents.contracts import DocumentLocation, DownloadedDocument, ExtractedPage
from pci.documents.eligibility import evaluate_corpus_eligibility
from pci.documents.service import prepare_document_text
from pci.models.documents import DocumentTextScope, SourceDocumentStatus
from pci.models.enums import ProductionType, RightsPolicy
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import RawRecord, Source


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(
        self, key: str, content: bytes, media_type: str, metadata: dict[str, str]
    ) -> None:
        self.objects[key] = content

    def get_object(self, key: str) -> bytes:
        return self.objects[key]


class FakeLocator:
    def __init__(self, location: DocumentLocation | None) -> None:
        self.location = location
        self.calls = 0

    def locate(self, raw: RawRecord) -> DocumentLocation | None:
        self.calls += 1
        return self.location


class FakeExtractor:
    def __init__(self, pages: tuple[ExtractedPage, ...]) -> None:
        self.pages = pages

    def extract(self, content: bytes) -> tuple[ExtractedPage, ...]:
        return self.pages


def eligible_version(
    session: Session,
    *,
    rights_policy: RightsPolicy = RightsPolicy.OPEN_COPY,
    production_type: ProductionType = ProductionType.THESIS,
    publication_year: int = 2024,
    abstract: str | None = "Resumo suficientemente informativo.",
    raw_rights_snapshot: str | None = None,
    schedule_overrides: dict[str, object] | None = None,
) -> tuple[ProductionVersion, Source]:
    schedule: dict[str, object] = {
        "institution_sector": "public",
        "institution_state": "PE",
        "corpus_types": ["thesis", "dissertation"],
        "analysis_year_start": 2016,
        "analysis_year_end": 2025,
        "current_year": 2026,
    }
    schedule.update(schedule_overrides or {})
    source = Source(
        code=f"source-{uuid.uuid4()}",
        name="Instituição pública pernambucana",
        connector_type="oai_pmh",
        base_url="https://repositorio.example/oai/request",
        rights_policy=rights_policy,
        schedule=schedule,
    )
    raw = RawRecord(
        source=source,
        source_identifier=f"oai:fixture:{uuid.uuid4()}",
        payload={},
        source_url="https://repositorio.example/items/42",
        checksum=uuid.uuid4().hex,
        rights_snapshot=raw_rights_snapshot or rights_policy.value,
    )
    production = Production(canonical_key=f"local:{uuid.uuid4()}")
    session.add_all([raw, production])
    session.flush()
    version = ProductionVersion(
        production_id=production.id,
        raw_record_id=raw.id,
        version=1,
        title="Pesquisa aplicada",
        abstract=abstract,
        publication_year=publication_year,
        type=production_type,
    )
    session.add(version)
    session.flush()
    return version, source


@pytest.mark.parametrize(
    ("year", "expected_layer"), [(2016, "analysis"), (2025, "analysis"), (2026, "current")]
)
def test_eligibility_accepts_only_configured_temporal_layers(
    session: Session, year: int, expected_layer: str
) -> None:
    version, source = eligible_version(session, publication_year=year)

    result = evaluate_corpus_eligibility(version, source)

    assert result.eligible is True
    assert result.layer == expected_layer
    assert result.reasons == ()


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"production_type": ProductionType.ARTICLE}, "production_type_not_in_corpus"),
        ({"publication_year": 2015}, "publication_year_outside_corpus"),
        ({"schedule_overrides": {"institution_sector": "private"}}, "institution_not_public"),
        ({"schedule_overrides": {"institution_state": "SP"}}, "institution_not_in_pe"),
        ({"schedule_overrides": {"analysis_year_start": 2027}}, "scope_configuration_invalid"),
    ],
)
def test_ineligible_records_return_an_explicit_reason(
    session: Session, kwargs: dict[str, object], reason: str
) -> None:
    version, source = eligible_version(session, **kwargs)  # type: ignore[arg-type]

    result = evaluate_corpus_eligibility(version, source)

    assert result.eligible is False
    assert reason in result.reasons


def test_restricted_rights_create_no_document_bytes(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    version, _ = eligible_version(session, rights_policy=RightsPolicy.METADATA_ONLY)
    locator = FakeLocator(
        DocumentLocation(
            url="https://repositorio.example/tese.pdf",
            media_type="application/pdf",
            rights="metadata-only",
        )
    )
    store = MemoryObjectStore()

    result = prepare_document_text(
        session,
        version.id,
        locator=locator,
        object_store=store,
        extractor=FakeExtractor(()),
    )

    assert result.source_document.status == SourceDocumentStatus.RESTRICTED
    assert result.text_version is not None
    assert result.text_version.scope is DocumentTextScope.ABSTRACT_ONLY
    assert locator.calls == 0
    assert store.objects == {}


def test_item_level_restriction_vetoes_source_copy_policy_and_keeps_labeled_abstract(
    session: Session,
) -> None:
    version, _ = eligible_version(
        session,
        rights_policy=RightsPolicy.OPEN_COPY,
        raw_rights_snapshot=RightsPolicy.METADATA_ONLY.value,
    )
    locator = FakeLocator(None)
    store = MemoryObjectStore()

    result = prepare_document_text(
        session,
        version.id,
        locator=locator,
        object_store=store,
        extractor=FakeExtractor(()),
    )

    assert result.source_document is not None
    assert result.source_document.status is SourceDocumentStatus.RESTRICTED
    assert result.text_version is not None
    assert result.text_version.scope is DocumentTextScope.ABSTRACT_ONLY
    assert locator.calls == 0
    assert store.objects == {}


def test_unavailable_full_text_falls_back_to_labeled_abstract(session: Session) -> None:
    version, _ = eligible_version(session)
    result = prepare_document_text(
        session,
        version.id,
        locator=FakeLocator(None),
        object_store=MemoryObjectStore(),
        extractor=FakeExtractor(()),
    )

    assert result.source_document is not None
    assert result.source_document.status is SourceDocumentStatus.FAILED
    assert result.text_version is not None
    assert result.text_version.scope is DocumentTextScope.ABSTRACT_ONLY


def test_scanned_pdf_enters_ocr_queue_but_abstract_remains_usable(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    version, _ = eligible_version(session)
    locator = FakeLocator(
        DocumentLocation(
            url="https://repositorio.example/tese.pdf",
            media_type="application/pdf",
            rights="open-copy",
        )
    )
    monkeypatch.setattr(
        "pci.documents.service.download_pdf",
        lambda *args, **kwargs: DownloadedDocument(
            content=b"%PDF-image-only",
            media_type="application/pdf",
            final_url="https://repositorio.example/tese.pdf",
        ),
    )
    store = MemoryObjectStore()

    result = prepare_document_text(
        session,
        version.id,
        locator=locator,
        object_store=store,
        extractor=FakeExtractor((ExtractedPage(page_number=1, text="imagem"),)),
    )

    assert result.source_document.status == SourceDocumentStatus.OCR_REQUIRED
    assert result.text_version is not None
    assert result.text_version.scope == DocumentTextScope.ABSTRACT_ONLY
    assert result.text_version.normalized_text == version.abstract
    assert len(store.objects) == 1


def test_searchable_pdf_creates_full_text_with_exact_page_boundaries(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    version, _ = eligible_version(session)
    locator = FakeLocator(
        DocumentLocation(
            url="https://repositorio.example/tese.pdf",
            media_type="application/pdf",
            rights="open-copy",
        )
    )
    monkeypatch.setattr(
        "pci.documents.service.download_pdf",
        lambda *args, **kwargs: DownloadedDocument(
            content=b"%PDF-searchable",
            media_type="application/pdf",
            final_url="https://repositorio.example/tese.pdf",
        ),
    )
    first_page = "ação pública " * 15
    second_page = "evidência repetida " * 15

    result = prepare_document_text(
        session,
        version.id,
        locator=locator,
        object_store=MemoryObjectStore(),
        extractor=FakeExtractor(
            (
                ExtractedPage(page_number=1, text=first_page),
                ExtractedPage(page_number=2, text=second_page),
            )
        ),
    )

    assert result.source_document is not None
    assert result.source_document.status == SourceDocumentStatus.TEXT_EXTRACTED
    assert result.text_version is not None
    assert result.text_version.scope == DocumentTextScope.FULL_TEXT
    assert result.text_version.normalized_text == f"{first_page}\n{second_page}"
    assert [
        result.text_version.normalized_text[page.start_offset : page.end_offset]
        for page in result.text_version.pages
    ] == [first_page, second_page]


def test_ineligible_record_creates_no_document_work(session: Session) -> None:
    version, _ = eligible_version(session, production_type=ProductionType.ARTICLE)
    locator = FakeLocator(None)
    store = MemoryObjectStore()

    result = prepare_document_text(
        session,
        version.id,
        locator=locator,
        object_store=store,
        extractor=FakeExtractor(()),
    )

    assert result.source_document is None
    assert result.text_version is None
    assert locator.calls == 0
    assert store.objects == {}
