import hashlib

import pytest
from sqlalchemy.orm import Session

from pci.claims.enums import CandidateStatus, ContributionField, ExtractionRunStatus
from pci.claims.service import run_extraction
from pci.contributions.service import (
    materialize_validated_contribution,
    record_field_decision,
)
from pci.models.claims import CandidateContribution, ExtractionRun
from pci.models.contributions import FieldDecisionAction
from pci.models.documents import (
    DocumentTextScope,
    DocumentTextVersion,
    SourceDocument,
    SourceDocumentStatus,
    TextExtractionMethod,
)
from pci.models.review import ReviewCase
from pci.review.service import complete_assignment
from tests.claims.test_extraction import active_assignment, deterministic_provider, ready_text


def test_materialization_rejects_candidates_from_multiple_document_text_versions(
    session: Session,
) -> None:
    first_text = ready_text(session)
    first_run = run_extraction(session, first_text.id, deterministic_provider(first_text))
    first_candidate = (
        session.query(CandidateContribution).filter_by(extraction_run_id=first_run.id).one()
    )
    document = SourceDocument(
        production_version_id=first_text.production_version_id,
        status=SourceDocumentStatus.TEXT_EXTRACTED,
    )
    session.add(document)
    session.flush()
    second_value = "Outra extração textual da mesma produção."
    second_text = DocumentTextVersion(
        source_document_id=document.id,
        production_version_id=first_text.production_version_id,
        version=2,
        normalized_text=second_value,
        scope=DocumentTextScope.FULL_TEXT,
        extraction_method=TextExtractionMethod.MANUAL,
        checksum=hashlib.sha256(second_value.encode()).hexdigest(),
    )
    session.add(second_text)
    session.flush()
    second_run = ExtractionRun(
        document_text_version_id=second_text.id,
        document_checksum=second_text.checksum,
        provider="fixture",
        model="fixture",
        schema_version="v1",
        instruction_version="v1",
        status=ExtractionRunStatus.SUCCEEDED,
    )
    session.add(second_run)
    session.flush()
    second_candidate = CandidateContribution(
        extraction_run_id=second_run.id,
        ordinal=1,
        status=CandidateStatus.GENERATED,
    )
    session.add(second_candidate)
    session.flush()
    assignment, curator = active_assignment(session, first_candidate)
    review_case = session.get(ReviewCase, assignment.review_case_id)
    assert review_case is not None
    review_case.candidate_ids = [str(first_candidate.id), str(second_candidate.id)]
    for field in ContributionField:
        record_field_decision(
            session,
            assignment.id,
            field,
            FieldDecisionAction.REJECT,
            None,
            [],
            "Não sustentado.",
            curator,
        )
    complete_assignment(session, assignment.id, curator)

    with pytest.raises(ValueError, match="single document text version"):
        materialize_validated_contribution(session, review_case.id, curator)
