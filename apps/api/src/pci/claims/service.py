import hashlib
import json
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session

from pci.claims import repository
from pci.claims.contracts import (
    DocumentPagePayload,
    ExtractionDocument,
    ExtractionProvider,
    ProviderExtraction,
)
from pci.claims.enums import (
    CandidateStatus,
    ContributionField,
    ContributionType,
    ExtractionRunStatus,
)
from pci.claims.providers import ProviderError
from pci.models.base import utc_now
from pci.models.claims import (
    CandidateClaim,
    CandidateContribution,
    CandidateGrounding,
    ExtractionRun,
)
from pci.models.documents import DocumentTextScope, DocumentTextVersion

MAX_RAW_RESPONSE_BYTES = 65_536


class InvalidGroundingError(ValueError):
    pass


def validate_provider_extraction(
    document: ExtractionDocument, extraction: ProviderExtraction
) -> None:
    pages = {page.page_number: page for page in document.pages}
    for contribution in extraction.contributions:
        for claim in contribution.claims:
            for grounding in claim.groundings:
                if grounding.document_text_version_id != document.document_text_version_id:
                    raise InvalidGroundingError("grounding references another document")
                if not (0 <= grounding.start_offset < grounding.end_offset <= len(document.normalized_text)):
                    raise InvalidGroundingError("grounding offsets are outside document")
                exact_quote = document.normalized_text[
                    grounding.start_offset : grounding.end_offset
                ]
                if grounding.quote != exact_quote:
                    raise InvalidGroundingError("grounding quote does not match exact slice")
                if document.scope is DocumentTextScope.ABSTRACT_ONLY:
                    if grounding.page_number is not None or grounding.section != "abstract":
                        raise InvalidGroundingError("abstract grounding must use abstract section")
                    continue
                if grounding.page_number is None or grounding.page_number not in pages:
                    raise InvalidGroundingError("grounding page does not exist")
                page = pages[grounding.page_number]
                if grounding.start_offset < page.start_offset or grounding.end_offset > page.end_offset:
                    raise InvalidGroundingError("grounding crosses its referenced page")


def run_extraction(
    session: Session,
    document_text_version_id: uuid.UUID,
    provider: ExtractionProvider,
    *,
    rerun: bool = False,
) -> ExtractionRun:
    session.execute(repository.lock_document_text_version(document_text_version_id))
    text = session.get(DocumentTextVersion, document_text_version_id)
    if text is None:
        raise ValueError(f"document text version does not exist: {document_text_version_id}")
    existing = repository.current_completed_run(
        session, document_checksum=text.checksum, provider=provider
    )
    if existing is not None and not rerun:
        return existing
    previous = repository.latest_run(
        session, document_checksum=text.checksum, provider=provider
    )
    if rerun and previous is not None and previous.status in {
        ExtractionRunStatus.SUCCEEDED,
        ExtractionRunStatus.FAILED,
    }:
        previous.status = ExtractionRunStatus.SUPERSEDED
    run = ExtractionRun(
        document_text_version_id=text.id,
        document_checksum=text.checksum,
        provider=provider.provider_name,
        model=provider.model_name,
        schema_version=provider.schema_version,
        instruction_version=provider.instruction_version,
        status=ExtractionRunStatus.RUNNING,
        parameters={"rerun": rerun},
        supersedes_id=previous.id if rerun and previous is not None else None,
        started_at=utc_now(),
    )
    session.add(run)
    session.flush()
    document = _extraction_document(text)
    try:
        extraction = provider.extract(document)
        _validate_provider_identity(provider, extraction)
        validate_provider_extraction(document, extraction)
        raw_response = extraction.raw_response
        if raw_response is not None and len(
            json.dumps(raw_response, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ) > MAX_RAW_RESPONSE_BYTES:
            raise ValueError("raw response exceeds private reproducibility bound")
    except InvalidGroundingError:
        return _fail_run(session, run, "invalid_grounding")
    except (ProviderError, RuntimeError, ValidationError, ValueError, TypeError):
        return _fail_run(session, run, "provider_failure")

    run.raw_response = raw_response
    for contribution_ordinal, payload in enumerate(extraction.contributions, start=1):
        suggested_type = next(
            (
                ContributionType(claim.value)
                for claim in payload.claims
                if claim.field is ContributionField.CONTRIBUTION_TYPE
            ),
            None,
        )
        candidate = CandidateContribution(
            extraction_run_id=run.id,
            ordinal=contribution_ordinal,
            status=CandidateStatus.GENERATED,
            suggested_type=suggested_type,
        )
        session.add(candidate)
        session.flush()
        for claim_ordinal, claim_payload in enumerate(payload.claims, start=1):
            claim = CandidateClaim(
                candidate_contribution_id=candidate.id,
                ordinal=claim_ordinal,
                field=claim_payload.field,
                value=claim_payload.value,
                confidence=claim_payload.confidence,
                notes=claim_payload.notes,
            )
            session.add(claim)
            session.flush()
            session.add_all(
                [
                    CandidateGrounding(
                        candidate_claim_id=claim.id,
                        document_text_version_id=grounding.document_text_version_id,
                        page_number=grounding.page_number,
                        section=grounding.section,
                        start_offset=grounding.start_offset,
                        end_offset=grounding.end_offset,
                        quote=grounding.quote,
                        quote_hash=hashlib.sha256(grounding.quote.encode("utf-8")).hexdigest(),
                    )
                    for grounding in claim_payload.groundings
                ]
            )
    run.status = ExtractionRunStatus.SUCCEEDED
    run.completed_at = utc_now()
    session.flush()
    return run


def _extraction_document(text: DocumentTextVersion) -> ExtractionDocument:
    return ExtractionDocument(
        document_text_version_id=text.id,
        checksum=text.checksum,
        scope=text.scope,
        normalized_text=text.normalized_text,
        pages=[
            DocumentPagePayload(
                page_number=page.page_number,
                start_offset=page.start_offset,
                end_offset=page.end_offset,
            )
            for page in sorted(text.pages, key=lambda item: item.page_number)
        ],
    )


def _validate_provider_identity(
    provider: ExtractionProvider, extraction: ProviderExtraction
) -> None:
    if (
        extraction.provider != provider.provider_name
        or extraction.model != provider.model_name
        or extraction.schema_version != provider.schema_version
        or extraction.instruction_version != provider.instruction_version
    ):
        raise ValueError("provider response identity does not match request")


def _fail_run(session: Session, run: ExtractionRun, code: str) -> ExtractionRun:
    run.status = ExtractionRunStatus.FAILED
    run.error_code = code[:100]
    run.raw_response = None
    run.completed_at = utc_now()
    session.flush()
    return run
