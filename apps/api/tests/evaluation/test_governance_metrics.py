import hashlib
import uuid

from sqlalchemy.orm import Session

from pci.claims.enums import CandidateStatus, ContributionField, ExtractionRunStatus
from pci.evaluation.service import (
    compute_extraction_metrics,
    compute_governance_metrics,
    compute_inter_rater_agreement,
)
from pci.models.claims import CandidateClaim, CandidateContribution, ExtractionRun
from pci.models.contributions import (
    ContributionGrounding,
    ContributionVersion,
    ContributionVersionStatus,
    FieldDecisionAction,
    ReviewFieldDecision,
    ScientificContribution,
)
from pci.models.documents import (
    DocumentTextScope,
    DocumentTextVersion,
    SourceDocument,
    SourceDocumentStatus,
    TextExtractionMethod,
)
from pci.models.enums import ProductionType, RightsPolicy
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import RawRecord, Source
from pci.models.publication import PublishedContribution
from pci.models.review import (
    ReviewAssignment,
    ReviewCase,
    ReviewCaseKind,
    ReviewLane,
    ReviewStatus,
    SampleSplit,
    SamplingRun,
)


def _candidate_context(
    session: Session,
) -> tuple[CandidateContribution, DocumentTextVersion, Production]:
    source = Source(
        code=f"evaluation-{uuid.uuid4()}",
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
        knowledge_areas=["Ciência da Informação"],
    )
    session.add(production_version)
    session.flush()
    document = SourceDocument(
        production_version_id=production_version.id,
        status=SourceDocumentStatus.TEXT_EXTRACTED,
    )
    session.add(document)
    session.flush()
    text_value = "Problema público e solução científica documentada."
    text = DocumentTextVersion(
        source_document_id=document.id,
        production_version_id=production_version.id,
        version=1,
        normalized_text=text_value,
        scope=DocumentTextScope.FULL_TEXT,
        extraction_method=TextExtractionMethod.MANUAL,
        checksum=hashlib.sha256(text_value.encode()).hexdigest(),
    )
    session.add(text)
    session.flush()
    extraction = ExtractionRun(
        document_text_version_id=text.id,
        document_checksum=text.checksum,
        provider="fixture",
        model="fixture",
        schema_version="v1",
        instruction_version="v1",
        status=ExtractionRunStatus.SUCCEEDED,
    )
    session.add(extraction)
    session.flush()
    candidate = CandidateContribution(
        extraction_run_id=extraction.id,
        ordinal=1,
        status=CandidateStatus.GENERATED,
    )
    session.add(candidate)
    session.flush()
    return candidate, text, production


def _sampling_run(session: Session, selected_size: int = 1) -> SamplingRun:
    run = SamplingRun(
        target_size=selected_size,
        selected_size=selected_size,
        test_fraction="1",
        double_code_fraction="0",
        seed=str(uuid.uuid4()),
        rule_version="v1",
    )
    session.add(run)
    session.flush()
    return run


def test_empty_governance_metrics_do_not_turn_unknown_rates_into_zero(session: Session) -> None:
    run = SamplingRun(
        target_size=1,
        selected_size=0,
        test_fraction="1",
        double_code_fraction="1",
        seed="empty",
        rule_version="v1",
    )
    session.add(run)
    session.flush()

    governance = compute_governance_metrics(session, run.id)
    agreement = compute_inter_rater_agreement(session, run.id)

    assert governance.return_rate is None
    assert governance.provenance_completeness is None
    assert all(item.agreement is None for item in agreement.by_field.values())


def test_extraction_metrics_use_all_merged_candidates_and_final_reference_only(
    session: Session,
) -> None:
    first, _, _ = _candidate_context(session)
    second = CandidateContribution(
        extraction_run_id=first.extraction_run_id,
        ordinal=2,
        status=CandidateStatus.GENERATED,
    )
    session.add(second)
    session.flush()
    session.add_all(
        [
            CandidateClaim(
                candidate_contribution_id=first.id,
                ordinal=1,
                field=ContributionField.DESCRIPTION,
                value="Solução",
                confidence=0.8,
            ),
            CandidateClaim(
                candidate_contribution_id=second.id,
                ordinal=1,
                field=ContributionField.PROBLEM_OR_PHENOMENON,
                value="Problema",
                confidence=0.8,
            ),
        ]
    )
    run = _sampling_run(session)
    case = ReviewCase(
        sampling_run_id=run.id,
        kind=ReviewCaseKind.CANDIDATE,
        candidate_contribution_id=first.id,
        candidate_ids=[str(first.id), str(second.id)],
        stratum={"institution": "UFPE", "text_scope": "full_text"},
        split=SampleSplit.TEST,
        priority_reason="test",
        selection_order=1,
    )
    session.add(case)
    session.flush()
    assignment = ReviewAssignment(
        review_case_id=case.id,
        lane=ReviewLane.SINGLE,
        status=ReviewStatus.COMPLETED,
        actor_key="test|curator",
    )
    session.add(assignment)
    session.flush()
    session.add_all(
        [
            ReviewFieldDecision(
                review_assignment_id=assignment.id,
                field=ContributionField.DESCRIPTION,
                sequence=1,
                action=FieldDecisionAction.ACCEPT,
                value="Solução",
                actor_key="test|curator",
            ),
            ReviewFieldDecision(
                review_assignment_id=assignment.id,
                field=ContributionField.PROBLEM_OR_PHENOMENON,
                sequence=1,
                action=FieldDecisionAction.ACCEPT,
                value="Problema",
                actor_key="test|curator",
            ),
        ]
    )
    session.flush()

    metrics = compute_extraction_metrics(session, run.id, SampleSplit.TEST)

    assert metrics.by_field["description"].true_positive == 1
    assert metrics.by_field["problem_or_phenomenon"].true_positive == 1
    assert len(metrics.by_stratum) == 1
    stratum_metrics = next(iter(metrics.by_stratum.values()))
    assert stratum_metrics["description"].true_positive == 1
    assert stratum_metrics["problem_or_phenomenon"].true_positive == 1


def test_primary_review_without_adjudication_is_not_a_reference_standard(
    session: Session,
) -> None:
    candidate, _, _ = _candidate_context(session)
    session.add(
        CandidateClaim(
            candidate_contribution_id=candidate.id,
            ordinal=1,
            field=ContributionField.DESCRIPTION,
            value="Solução",
            confidence=0.8,
        )
    )
    run = _sampling_run(session)
    case = ReviewCase(
        sampling_run_id=run.id,
        kind=ReviewCaseKind.CANDIDATE,
        candidate_contribution_id=candidate.id,
        candidate_ids=[str(candidate.id)],
        stratum={"institution": "UFPE"},
        split=SampleSplit.TEST,
        priority_reason="test",
        selection_order=1,
    )
    session.add(case)
    session.flush()
    session.add(
        ReviewAssignment(
            review_case_id=case.id,
            lane=ReviewLane.PRIMARY,
            status=ReviewStatus.COMPLETED,
            actor_key="test|primary",
        )
    )
    session.flush()

    metrics = compute_extraction_metrics(session, run.id, SampleSplit.TEST)

    assert metrics.record_ids == set()
    assert metrics.by_field["description"].predicted_positive == 0


def test_governance_provenance_is_measured_per_published_scientific_field(
    session: Session,
) -> None:
    candidate, text, production = _candidate_context(session)
    run = _sampling_run(session)
    case = ReviewCase(
        sampling_run_id=run.id,
        kind=ReviewCaseKind.CANDIDATE,
        candidate_contribution_id=candidate.id,
        candidate_ids=[str(candidate.id)],
        stratum={"institution": "UFPE"},
        split=SampleSplit.TEST,
        priority_reason="test",
        selection_order=1,
    )
    session.add(case)
    session.flush()
    contribution = ScientificContribution(production_id=production.id, current_version_number=1)
    session.add(contribution)
    session.flush()
    version = ContributionVersion(
        scientific_contribution_id=contribution.id,
        version=1,
        status=ContributionVersionStatus.PUBLISHED,
        review_case_id=case.id,
        created_by="test|curator",
        description="Solução",
        problem_or_phenomenon="Problema",
    )
    session.add(version)
    session.flush()
    session.add_all(
        [
            ContributionGrounding(
                contribution_version_id=version.id,
                field=ContributionField.DESCRIPTION,
                source_scope="full_text",
                document_text_version_id=text.id,
                start_offset=0,
                end_offset=8,
                quote="Problema",
                quote_hash=hashlib.sha256(b"Problema").hexdigest(),
            ),
            PublishedContribution(
                scientific_contribution_id=contribution.id,
                contribution_version_id=version.id,
                production_id=production.id,
                version=1,
                scientific_values={
                    "description": "Solução",
                    "problem_or_phenomenon": "Problema",
                },
                approved_groundings=[],
                active=True,
            ),
        ]
    )
    session.flush()

    metrics = compute_governance_metrics(session, run.id)

    assert metrics.provenance_completeness == 0.5
