import hashlib
import uuid

import pytest
from sqlalchemy.orm import Session

from pci.auth.contracts import AuthPrincipal, Role
from pci.claims.contracts import (
    CandidateClaimPayload,
    CandidateContributionPayload,
    GroundingPayload,
    ProviderExtraction,
)
from pci.claims.enums import ContributionField, ExtractionRunStatus
from pci.claims.providers import DeterministicExtractionProvider
from pci.claims.service import run_extraction
from pci.contributions.service import MissingGroundingError, record_field_decision
from pci.models.base import AppendOnlyViolation
from pci.models.claims import (
    CandidateClaim,
    CandidateContribution,
    CandidateGrounding,
    ExtractionRun,
)
from pci.models.contributions import FieldDecisionAction
from pci.models.documents import (
    DocumentPage,
    DocumentTextScope,
    DocumentTextVersion,
    SourceDocument,
    SourceDocumentStatus,
    TextExtractionMethod,
)
from pci.models.enums import ProductionType, RightsPolicy
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import RawRecord, Source
from pci.models.review import (
    ReviewAssignment,
    ReviewCase,
    ReviewCaseKind,
    ReviewLane,
    ReviewStatus,
    SampleSplit,
    SamplingRun,
)


def ready_text(session: Session) -> DocumentTextVersion:
    source = Source(
        code=f"source-{uuid.uuid4()}",
        name="UFPE",
        connector_type="fixture",
        rights_policy=RightsPolicy.OPEN_COPY,
    )
    raw = RawRecord(
        source=source,
        source_identifier=str(uuid.uuid4()),
        payload={},
        checksum=uuid.uuid4().hex,
    )
    production = Production(canonical_key=f"local:{uuid.uuid4()}")
    session.add_all([raw, production])
    session.flush()
    production_version = ProductionVersion(
        production_id=production.id,
        raw_record_id=raw.id,
        version=1,
        title="Tese",
        publication_year=2024,
        type=ProductionType.THESIS,
    )
    session.add(production_version)
    session.flush()
    source_document = SourceDocument(
        production_version_id=production_version.id,
        status=SourceDocumentStatus.TEXT_EXTRACTED,
    )
    session.add(source_document)
    session.flush()
    text = "A tecnologia reduziu o tempo de espera em unidades públicas. " * 5
    text_version = DocumentTextVersion(
        source_document_id=source_document.id,
        production_version_id=production_version.id,
        version=1,
        normalized_text=text,
        scope=DocumentTextScope.FULL_TEXT,
        extraction_method=TextExtractionMethod.PYPDF,
        checksum=hashlib.sha256(text.encode()).hexdigest(),
        pages=[
            DocumentPage(
                page_number=1,
                start_offset=0,
                end_offset=len(text),
                checksum=hashlib.sha256(text.encode()).hexdigest(),
            )
        ],
    )
    session.add(text_version)
    session.flush()
    return text_version


def deterministic_provider(text: DocumentTextVersion) -> DeterministicExtractionProvider:
    quote = "reduziu o tempo de espera"
    start = text.normalized_text.index(quote)
    extraction = ProviderExtraction(
        provider="deterministic",
        model="fixture-v1",
        schema_version="v1",
        instruction_version="v1",
        contributions=[
            CandidateContributionPayload(
                claims=[
                    CandidateClaimPayload(
                        field=ContributionField.EVIDENCE_RESULTS,
                        value="Redução do tempo de espera",
                        confidence=0.9,
                        groundings=[
                            GroundingPayload(
                                document_text_version_id=text.id,
                                page_number=1,
                                start_offset=start,
                                end_offset=start + len(quote),
                                quote=quote,
                            )
                        ],
                    )
                ]
            )
        ],
        raw_response={"private": "reproducible"},
    )
    return DeterministicExtractionProvider({text.checksum: extraction})


def test_duplicate_extraction_is_idempotent(session: Session) -> None:
    text = ready_text(session)
    provider = deterministic_provider(text)

    first = run_extraction(session, text.id, provider)
    second = run_extraction(session, text.id, provider)

    assert first is second
    assert first.status == ExtractionRunStatus.SUCCEEDED
    assert session.query(CandidateContribution).count() == 1


def test_explicit_rerun_preserves_and_supersedes_the_prior_run(session: Session) -> None:
    text = ready_text(session)
    provider = deterministic_provider(text)
    first = run_extraction(session, text.id, provider)

    second = run_extraction(session, text.id, provider, rerun=True)

    assert first.id != second.id
    assert second.supersedes_id == first.id
    assert session.get(ExtractionRun, first.id) is first
    assert first.status == ExtractionRunStatus.SUPERSEDED
    assert second.status == ExtractionRunStatus.SUCCEEDED


class FailingProvider:
    provider_name = "failing"
    model_name = "fixture"
    schema_version = "v1"
    instruction_version = "v1"

    def extract(self, document: object) -> ProviderExtraction:
        raise RuntimeError("secret-key-must-not-be-persisted")


def test_provider_failure_creates_private_failed_run_without_candidates(
    session: Session,
) -> None:
    text = ready_text(session)

    run = run_extraction(session, text.id, FailingProvider())

    assert run.status == ExtractionRunStatus.FAILED
    assert run.error_code == "provider_failure"
    assert "secret" not in str(run.raw_response)
    assert session.query(CandidateContribution).count() == 0


def test_candidate_claim_payload_is_append_only(session: Session) -> None:
    text = ready_text(session)
    run_extraction(session, text.id, deterministic_provider(text))
    claim = session.query(CandidateClaim).one()
    session.commit()

    claim.value = "tentativa de sobrescrita"
    with pytest.raises(AppendOnlyViolation):
        session.commit()


def active_assignment(
    session: Session, candidate: CandidateContribution
) -> tuple[ReviewAssignment, AuthPrincipal]:
    run = SamplingRun(
        target_size=1,
        selected_size=1,
        test_fraction="1",
        double_code_fraction="0",
        seed=uuid.uuid4().hex,
        rule_version="v1",
    )
    session.add(run)
    session.flush()
    review_case = ReviewCase(
        sampling_run_id=run.id,
        kind=ReviewCaseKind.CANDIDATE,
        candidate_contribution_id=candidate.id,
        candidate_ids=[str(candidate.id)],
        stratum={},
        split=SampleSplit.TEST,
        priority_reason="integrity-test",
        selection_order=1,
    )
    session.add(review_case)
    session.flush()
    principal = AuthPrincipal("test", "curator", None, frozenset({Role.CURATOR}))
    assignment = ReviewAssignment(
        review_case_id=review_case.id,
        lane=ReviewLane.SINGLE,
        status=ReviewStatus.ASSIGNED,
        actor_key=principal.actor_key,
    )
    session.add(assignment)
    session.flush()
    return assignment, principal


def test_field_decision_rejects_foreign_or_missing_grounding_and_altered_accept_value(
    session: Session,
) -> None:
    own_text = ready_text(session)
    own_run = run_extraction(session, own_text.id, deterministic_provider(own_text))
    run_extraction(session, own_text.id, deterministic_provider(own_text), rerun=True)
    own_candidate = (
        session.query(CandidateContribution).filter_by(extraction_run_id=own_run.id).one()
    )
    own_grounding = (
        session.query(CandidateGrounding)
        .join(CandidateClaim)
        .filter(CandidateClaim.candidate_contribution_id == own_candidate.id)
        .one()
    )
    foreign_grounding = (
        session.query(CandidateGrounding).filter(CandidateGrounding.id != own_grounding.id).one()
    )
    assignment, principal = active_assignment(session, own_candidate)

    for grounding_ids, value in (
        ([], None),
        ([foreign_grounding.id], None),
        ([own_grounding.id], "Valor inventado"),
    ):
        with pytest.raises(MissingGroundingError):
            record_field_decision(
                session,
                assignment.id,
                ContributionField.EVIDENCE_RESULTS,
                FieldDecisionAction.ACCEPT,
                value,
                grounding_ids,
                None,
                principal,
            )

    decision = record_field_decision(
        session,
        assignment.id,
        ContributionField.EVIDENCE_RESULTS,
        FieldDecisionAction.ACCEPT,
        None,
        [own_grounding.id],
        None,
        principal,
    )
    assert decision.value == "Redução do tempo de espera"


def test_correction_grounding_must_match_the_governed_field(session: Session) -> None:
    text = ready_text(session)
    extraction = run_extraction(session, text.id, deterministic_provider(text))
    candidate = (
        session.query(CandidateContribution).filter_by(extraction_run_id=extraction.id).one()
    )
    grounding = session.query(CandidateGrounding).one()
    assignment, principal = active_assignment(session, candidate)

    with pytest.raises(MissingGroundingError):
        record_field_decision(
            session,
            assignment.id,
            ContributionField.DESCRIPTION,
            FieldDecisionAction.CORRECT,
            "Descrição",
            [grounding.id],
            "Correção",
            principal,
        )


def test_negative_decision_does_not_retain_selected_grounding(session: Session) -> None:
    text = ready_text(session)
    extraction = run_extraction(session, text.id, deterministic_provider(text))
    candidate = (
        session.query(CandidateContribution).filter_by(extraction_run_id=extraction.id).one()
    )
    grounding = session.query(CandidateGrounding).one()
    assignment, principal = active_assignment(session, candidate)

    decision = record_field_decision(
        session,
        assignment.id,
        ContributionField.EVIDENCE_RESULTS,
        FieldDecisionAction.REJECT,
        None,
        [grounding.id],
        "A evidência foi rejeitada.",
        principal,
    )

    assert decision.grounding_ids is None

def test_disabled_provider_does_not_create_unvalidated_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pci.claims import tasks

    monkeypatch.setenv("CLAIMS_PROVIDER", "disabled")
    monkeypatch.setattr(
        tasks,
        "Settings",
        lambda: type("DisabledSettings", (), {"claims_provider": "disabled"})(),
    )

    assert tasks.extract_document_task.fn(str(uuid.uuid4())) is None

