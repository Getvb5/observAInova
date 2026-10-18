from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.auth.contracts import AuthPrincipal, Role
from pci.claims.enums import ContributionField
from pci.claims.service import run_extraction
from pci.contributions.service import (
    materialize_validated_contribution,
    record_field_decision,
)
from pci.models.claims import CandidateContribution, CandidateGrounding
from pci.models.contributions import (
    ContributionGrounding,
    ContributionVersion,
    ContributionVersionStatus,
    FieldDecisionAction,
    ScientificContribution,
)
from pci.models.publication import PublicationAction, PublicationOutbox
from pci.models.review import ReviewCase, ReviewCaseKind
from pci.publication.service import decide_publication, process_publication_event
from pci.review.service import claim_next_assignment, complete_assignment
from tests.claims.test_extraction import active_assignment, deterministic_provider, ready_text


def curator(subject: str) -> AuthPrincipal:
    return AuthPrincipal("test", subject, None, frozenset({Role.CURATOR}))


def test_returned_version_opens_and_materializes_a_grounded_corrective_revision(
    session: Session,
) -> None:
    text = ready_text(session)
    extraction = run_extraction(session, text.id, deterministic_provider(text))
    candidate = session.scalar(
        select(CandidateContribution).where(
            CandidateContribution.extraction_run_id == extraction.id
        )
    )
    grounding = session.scalar(select(CandidateGrounding))
    assert candidate is not None and grounding is not None
    first_assignment, first_curator = active_assignment(session, candidate)
    for field in ContributionField:
        if field is ContributionField.EVIDENCE_RESULTS:
            record_field_decision(
                session,
                first_assignment.id,
                field,
                FieldDecisionAction.ACCEPT,
                None,
                [grounding.id],
                None,
                first_curator,
            )
        else:
            record_field_decision(
                session,
                first_assignment.id,
                field,
                FieldDecisionAction.REJECT,
                None,
                [],
                "Não sustentado.",
                first_curator,
            )
    complete_assignment(session, first_assignment.id, first_curator)
    first = materialize_validated_contribution(
        session, first_assignment.review_case_id, first_curator
    )
    supervisor = AuthPrincipal("test", "supervisor", None, frozenset({Role.SUPERVISOR}))
    decision = decide_publication(
        session,
        first.id,
        PublicationAction.RETURN,
        "Revalidar a interpretação da evidência.",
        supervisor,
    )
    event = session.scalar(
        select(PublicationOutbox).where(PublicationOutbox.publication_decision_id == decision.id)
    )
    assert event is not None
    process_publication_event(session, event.id)

    second_curator = curator("corrector")
    correction_assignment = claim_next_assignment(session, second_curator)
    assert correction_assignment is not None
    correction_case = session.get(ReviewCase, correction_assignment.review_case_id)
    assert correction_case is not None
    assert correction_case.kind is ReviewCaseKind.RETURN_CORRECTION
    for field in ContributionField:
        if field is ContributionField.EVIDENCE_RESULTS:
            record_field_decision(
                session,
                correction_assignment.id,
                field,
                FieldDecisionAction.CORRECT,
                "Redução observada do tempo de espera",
                [grounding.id],
                "Formulação mais fiel ao resultado.",
                second_curator,
            )
        else:
            record_field_decision(
                session,
                correction_assignment.id,
                field,
                FieldDecisionAction.REJECT,
                None,
                [],
                "Não sustentado.",
                second_curator,
            )
    complete_assignment(session, correction_assignment.id, second_curator)
    second = materialize_validated_contribution(session, correction_case.id, second_curator)

    contribution = session.get(ScientificContribution, first.scientific_contribution_id)
    assert contribution is not None
    assert first.status is ContributionVersionStatus.RETURNED
    assert first.evidence_results == "Redução do tempo de espera"
    assert second.status is ContributionVersionStatus.VALIDATED
    assert second.version == 2
    assert second.base_version_id == first.id
    assert second.evidence_results == "Redução observada do tempo de espera"
    assert contribution.current_version_number == 2
    assert (
        session.scalar(
            select(ContributionGrounding).where(
                ContributionGrounding.contribution_version_id == second.id,
                ContributionGrounding.field == ContributionField.EVIDENCE_RESULTS,
            )
        )
        is not None
    )
    assert (
        session.scalar(
            select(ContributionVersion).where(
                ContributionVersion.review_case_id == correction_case.id
            )
        )
        is second
    )
