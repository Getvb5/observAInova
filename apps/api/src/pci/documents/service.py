import hashlib
import uuid
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from pypdf.errors import PdfReadError
from sqlalchemy.orm import Session

from pci.documents import repository
from pci.documents.contracts import (
    DocumentLocator,
    DocumentPreparationResult,
    PdfTextExtractor,
)
from pci.documents.eligibility import evaluate_corpus_eligibility
from pci.documents.locators import (
    DocumentAcquisitionError,
    document_allowed_hosts,
    download_pdf,
)
from pci.documents.text import normalize_extracted_pages, normalize_plain_text
from pci.models.documents import (
    DocumentPage,
    DocumentTextScope,
    DocumentTextVersion,
    SourceDocument,
    SourceDocumentStatus,
    TextExtractionMethod,
)
from pci.storage.objects import COPY_POLICIES, ObjectStore

MIN_SEARCHABLE_CHARACTERS = 200
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024


def prepare_document_text(
    session: Session,
    production_version_id: uuid.UUID,
    locator: DocumentLocator,
    object_store: ObjectStore,
    extractor: PdfTextExtractor,
    *,
    max_document_bytes: int = MAX_DOCUMENT_BYTES,
    download_timeout: float = 30.0,
) -> DocumentPreparationResult:
    version, raw, source = repository.get_document_context(session, production_version_id)
    eligibility = evaluate_corpus_eligibility(version, source)
    if not eligibility.eligible:
        return DocumentPreparationResult(eligibility, None, None)
    if source.rights_policy not in COPY_POLICIES or _rights_restrict_copy(raw.rights_snapshot):
        document = SourceDocument(
            production_version_id=version.id,
            status=SourceDocumentStatus.RESTRICTED,
            rights_snapshot=raw.rights_snapshot or source.rights_policy.value,
            error_code="copy_not_permitted",
        )
        session.add(document)
        session.flush()
        return DocumentPreparationResult(
            eligibility, document, _abstract_fallback(session, document, version)
        )

    location = locator.locate(raw)
    if location is None:
        document = SourceDocument(
            production_version_id=version.id,
            status=SourceDocumentStatus.FAILED,
            rights_snapshot=raw.rights_snapshot,
            error_code="document_not_found",
        )
        session.add(document)
        session.flush()
        return DocumentPreparationResult(
            eligibility, document, _abstract_fallback(session, document, version)
        )

    if _rights_restrict_copy(location.rights):
        document = SourceDocument(
            production_version_id=version.id,
            status=SourceDocumentStatus.RESTRICTED,
            official_url=location.url,
            rights_snapshot=location.rights,
            error_code="item_copy_not_permitted",
        )
        session.add(document)
        session.flush()
        return DocumentPreparationResult(
            eligibility, document, _abstract_fallback(session, document, version)
        )

    try:
        downloaded = download_pdf(
            location.url,
            allowed_hosts=document_allowed_hosts(raw),
            max_bytes=max_document_bytes,
            timeout=download_timeout,
        )
    except DocumentAcquisitionError as exc:
        document = SourceDocument(
            production_version_id=version.id,
            status=SourceDocumentStatus.FAILED,
            official_url=location.url,
            same_origin_host=urlsplit(location.url).hostname,
            rights_snapshot=location.rights or raw.rights_snapshot,
            error_code=exc.code,
        )
        session.add(document)
        session.flush()
        return DocumentPreparationResult(
            eligibility, document, _abstract_fallback(session, document, version)
        )

    checksum = hashlib.sha256(downloaded.content).hexdigest()
    object_key = f"documents/{version.id}/{checksum}.pdf"
    document = SourceDocument(
        production_version_id=version.id,
        status=SourceDocumentStatus.RETRIEVED,
        official_url=downloaded.final_url,
        same_origin_host=urlsplit(downloaded.final_url).hostname,
        object_key=object_key,
        object_checksum=checksum,
        media_type=downloaded.media_type,
        size_bytes=len(downloaded.content),
        rights_snapshot=location.rights or raw.rights_snapshot,
    )
    session.add(document)
    session.flush()
    try:
        prepared = normalize_extracted_pages(extractor.extract(downloaded.content))
    except (PdfReadError, OSError, ValueError):
        document.status = SourceDocumentStatus.FAILED
        document.error_code = "text_extraction_failed"
        session.flush()
        return DocumentPreparationResult(
            eligibility, document, _abstract_fallback(session, document, version)
        )

    try:
        object_store.put_object(
            object_key,
            downloaded.content,
            downloaded.media_type,
            {"checksum": checksum, "source_document_id": str(document.id)},
        )
    except (BotoCoreError, ClientError, OSError, ValueError):
        document.status = SourceDocumentStatus.FAILED
        document.error_code = "object_store_failed"
        session.flush()
        return DocumentPreparationResult(
            eligibility, document, _abstract_fallback(session, document, version)
        )

    searchable_characters = sum(not character.isspace() for character in prepared.normalized_text)
    if searchable_characters < MIN_SEARCHABLE_CHARACTERS:
        document.status = SourceDocumentStatus.OCR_REQUIRED
        text_version = _abstract_fallback(session, document, version)
    else:
        document.status = SourceDocumentStatus.TEXT_EXTRACTED
        text_version = DocumentTextVersion(
            source_document_id=document.id,
            production_version_id=version.id,
            version=repository.next_text_version(session, version.id),
            normalized_text=prepared.normalized_text,
            scope=DocumentTextScope.FULL_TEXT,
            extraction_method=TextExtractionMethod.PYPDF,
            checksum=prepared.checksum,
            pages=[
                DocumentPage(
                    page_number=page.page_number,
                    start_offset=page.start_offset,
                    end_offset=page.end_offset,
                    checksum=page.checksum,
                )
                for page in prepared.pages
            ],
        )
        session.add(text_version)
    session.flush()
    return DocumentPreparationResult(eligibility, document, text_version)


def _rights_restrict_copy(snapshot: str | None) -> bool:
    if not snapshot:
        return False
    normalized = snapshot.strip().casefold().replace("-", "_")
    return normalized in {
        "metadata_only",
        "link_only",
        "restricted",
        "no_copy",
        "copyright_restricted",
    }


def _abstract_fallback(
    session: Session,
    document: SourceDocument,
    version: object,
) -> DocumentTextVersion | None:
    from pci.models.production import ProductionVersion

    if not isinstance(version, ProductionVersion) or version.abstract is None:
        return None
    normalized_abstract = normalize_plain_text(version.abstract)
    text_version = DocumentTextVersion(
        source_document_id=document.id,
        production_version_id=version.id,
        version=repository.next_text_version(session, version.id),
        normalized_text=normalized_abstract,
        scope=DocumentTextScope.ABSTRACT_ONLY,
        extraction_method=TextExtractionMethod.METADATA_ABSTRACT,
        checksum=hashlib.sha256(normalized_abstract.encode("utf-8")).hexdigest(),
    )
    session.add(text_version)
    session.flush()
    return text_version
