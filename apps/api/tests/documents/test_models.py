import hashlib

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pci.models.base import AppendOnlyViolation
from pci.models.documents import (
    DocumentPage,
    DocumentTextScope,
    DocumentTextVersion,
    SourceDocument,
    SourceDocumentStatus,
    TextExtractionMethod,
)
from pci.models.production import Production, ProductionVersion


def production_version(session: Session) -> ProductionVersion:
    production = Production(canonical_key="local:document-model-test")
    version = ProductionVersion(
        production=production,
        version=1,
        title="Tese sobre ação pública",
        academic_program="Ciência da Informação",
        knowledge_areas=["Ciências Sociais Aplicadas", "Ciência da Informação"],
    )
    session.add(version)
    session.flush()
    return version


def ready_text_version(
    version: ProductionVersion,
    normalized_text: str,
    *,
    text_version: int = 1,
) -> DocumentTextVersion:
    content_digest = hashlib.sha256(normalized_text.encode()).hexdigest()
    document = SourceDocument(
        production_version=version,
        status=SourceDocumentStatus.TEXT_EXTRACTED,
        official_url="https://repositorio.example/document.pdf",
        same_origin_host="repositorio.example",
        object_key=f"documents/{content_digest}.pdf",
        object_checksum=hashlib.sha256(b"pdf").hexdigest(),
        media_type="application/pdf",
        size_bytes=3,
        rights_snapshot="open_copy",
    )
    return DocumentTextVersion(
        source_document=document,
        production_version=version,
        version=text_version,
        normalized_text=normalized_text,
        scope=DocumentTextScope.FULL_TEXT,
        extraction_method=TextExtractionMethod.PYPDF,
        checksum=content_digest,
        pages=[
            DocumentPage(
                page_number=1,
                start_offset=0,
                end_offset=len(normalized_text),
                checksum=content_digest,
            )
        ],
    )


def test_academic_metadata_is_optional_on_old_records(session: Session) -> None:
    production = Production(canonical_key="local:legacy-document")
    version = ProductionVersion(production=production, version=1, title="Registro anterior")
    session.add(version)
    session.commit()

    assert version.academic_program is None
    assert version.knowledge_areas is None


def test_document_text_is_append_only(session: Session) -> None:
    text = ready_text_version(production_version(session), "ação pública\nsegunda página")
    session.add(text)
    session.commit()

    text.normalized_text = "alterado"
    with pytest.raises(AppendOnlyViolation):
        session.commit()


def test_document_page_is_append_only(session: Session) -> None:
    text = ready_text_version(production_version(session), "ação pública")
    session.add(text)
    session.commit()

    page = text.pages[0]
    page.end_offset = 1
    with pytest.raises(AppendOnlyViolation):
        session.commit()


def test_text_versions_and_pages_have_scoped_unique_versions(session: Session) -> None:
    version = production_version(session)
    first = ready_text_version(version, "primeiro")
    second = ready_text_version(version, "segundo")
    session.add_all([first, second])

    with pytest.raises(IntegrityError):
        session.commit()


def test_document_page_requires_one_based_non_overlapping_offsets(session: Session) -> None:
    text = ready_text_version(production_version(session), "conteúdo")
    text.pages[0].page_number = 0
    session.add(text)

    with pytest.raises(IntegrityError):
        session.commit()
