from decimal import Decimal

from sqlalchemy.orm import Session

from pci.auth.contracts import AuthPrincipal, Role
from pci.claims.enums import CandidateStatus, ContributionField
from pci.contributions.service import record_field_decision
from pci.models.claims import CandidateContribution
from pci.models.contributions import FieldDecisionAction
from pci.models.review import ReviewAssignment, ReviewLane, ReviewStatus
from pci.review.sampling import SamplingConfig, create_stratified_sample
from pci.review.service import claim_next_assignment, complete_assignment

from .conftest import CandidateFactory


def principal(subject: str) -> AuthPrincipal:
    return AuthPrincipal(
        issuer="https://identity.example",
        subject=subject,
        display_name=None,
        roles=frozenset({Role.CURATOR}),
    )


def test_double_blind_lanes_cannot_be_claimed_by_the_same_actor(
    session: Session, candidate_factory: CandidateFactory
) -> None:
    candidate = candidate_factory()
    run = create_stratified_sample(
        session,
        [candidate.id],
        SamplingConfig(1, Decimal(0), Decimal(1), "seed", "v1"),
    )

    first = claim_next_assignment(session, principal("curator-one"))
    blocked = claim_next_assignment(session, principal("curator-one"))
    independent = claim_next_assignment(session, principal("curator-two"))

    assert first is not None
    assert blocked is None
    assert independent is not None
    assert first.review_case_id == independent.review_case_id == run.cases[0].id
    assert first.lane != independent.lane
    assert first.actor_key != independent.actor_key


def test_supervisor_only_identity_cannot_claim_curator_work(
    session: Session, candidate_factory: CandidateFactory
) -> None:
    candidate = candidate_factory()
    create_stratified_sample(
        session,
        [candidate.id],
        SamplingConfig(1, Decimal(0), Decimal(0), "seed", "v1"),
    )
    supervisor = AuthPrincipal(
        issuer="https://identity.example",
        subject="supervisor",
        display_name=None,
        roles=frozenset({Role.SUPERVISOR}),
    )

    assert claim_next_assignment(session, supervisor) is None


def _reject_every_field(
    session: Session,
    assignment: ReviewAssignment,
    actor: AuthPrincipal,
    reason: str = "não identificado",
) -> None:
    for field in ContributionField:
        record_field_decision(
            session,
            assignment.id,
            field,
            FieldDecisionAction.REJECT,
            None,
            [],
            reason,
            actor,
        )


def test_completed_independent_reviews_create_third_actor_adjudication(
    session: Session, candidate_factory: CandidateFactory
) -> None:
    candidate = candidate_factory()
    create_stratified_sample(
        session,
        [candidate.id],
        SamplingConfig(1, Decimal(0), Decimal(1), "adjudication", "v1"),
    )
    first_actor, second_actor = principal("one"), principal("two")
    first = claim_next_assignment(session, first_actor)
    second = claim_next_assignment(session, second_actor)
    assert first is not None and second is not None
    _reject_every_field(session, first, first_actor)
    complete_assignment(session, first.id, first_actor)
    _reject_every_field(session, second, second_actor, "ausente na segunda leitura")
    complete_assignment(session, second.id, second_actor)

    adjudication = (
        session.query(ReviewAssignment)
        .filter_by(review_case_id=first.review_case_id, lane=ReviewLane.ADJUDICATION)
        .one()
    )
    assert adjudication.status is ReviewStatus.PENDING
    assert claim_next_assignment(session, first_actor) is None
    third = claim_next_assignment(session, principal("three"))
    assert third is not None and third.id == adjudication.id
    from pci.routers.internal_contributions import _adjudication_context

    context = _adjudication_context(session, first.review_case_id)
    assert len(context["reviews"]) == 2
    assert set(context["disagreements"]) == {field.value for field in ContributionField}
    assert "actor" not in str(context).lower()


def test_merge_and_split_preserve_case_lineage_without_crossing_sample_split(
    session: Session, candidate_factory: CandidateFactory
) -> None:
    first = candidate_factory()
    second = CandidateContribution(
        extraction_run_id=first.extraction_run_id,
        ordinal=2,
        status=CandidateStatus.GENERATED,
        suggested_type=first.suggested_type,
    )
    session.add(second)
    session.flush()
    run = create_stratified_sample(
        session,
        [first.id, second.id],
        SamplingConfig(2, Decimal(1), Decimal(0), "lineage", "v1"),
    )
    from pci.contributions.service import merge_review_cases, split_review_case

    merged = merge_review_cases(session, [case.id for case in run.cases], principal("editor"))
    assert all(case.superseded_by_case_id == merged.id for case in run.cases)
    split = split_review_case(session, merged.id, [[first.id], [second.id]], principal("editor"))
    assert merged.superseded_by_case_id == split[0].id
    assert {tuple(case.candidate_ids or []) for case in split} == {
        (str(first.id),),
        (str(second.id),),
    }
