import uuid

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased

from pci.auth.contracts import AuthPrincipal, Role
from pci.models.base import utc_now
from pci.models.review import (
    ReviewAssignment,
    ReviewCase,
    ReviewCaseKind,
    ReviewLane,
    ReviewStatus,
)


def claim_next_assignment(session: Session, principal: AuthPrincipal) -> ReviewAssignment | None:
    if principal.roles.isdisjoint({Role.CURATOR, Role.ADMIN}):
        return None
    held_lane = aliased(ReviewAssignment)
    statement = (
        select(ReviewAssignment)
        .join(ReviewCase, ReviewCase.id == ReviewAssignment.review_case_id)
        .where(
            ReviewAssignment.status == ReviewStatus.PENDING,
            ReviewCase.kind.in_((ReviewCaseKind.CANDIDATE, ReviewCaseKind.RETURN_CORRECTION)),
            ~exists(
                select(held_lane.id).where(
                    held_lane.review_case_id == ReviewAssignment.review_case_id,
                    held_lane.actor_key == principal.actor_key,
                )
            ),
        )
        .order_by(ReviewCase.selection_order, ReviewAssignment.lane, ReviewAssignment.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    assignment = session.scalar(statement)
    if assignment is None:
        return None
    assignment.actor_key = principal.actor_key
    assignment.status = ReviewStatus.ASSIGNED
    assignment.claimed_at = utc_now()
    session.flush()
    return assignment


def complete_assignment(
    session: Session, assignment_id: uuid.UUID, principal: AuthPrincipal
) -> ReviewAssignment:
    assignment = session.get(ReviewAssignment, assignment_id)
    if assignment is None or assignment.actor_key != principal.actor_key:
        raise ValueError("assignment not found")
    if assignment.status not in {ReviewStatus.ASSIGNED, ReviewStatus.IN_REVIEW}:
        raise ValueError("assignment is not active")
    review_case = session.get(ReviewCase, assignment.review_case_id)
    if review_case is None or review_case.kind is ReviewCaseKind.SOURCE_REVALIDATION:
        raise ValueError("assignment is not a curatorial review")
    from pci.contributions.service import assert_review_complete

    assert_review_complete(session, assignment.id)
    assignment.status = ReviewStatus.COMPLETED
    assignment.completed_at = utc_now()
    session.flush()
    if assignment.lane in {ReviewLane.PRIMARY, ReviewLane.SECONDARY}:
        independent = session.scalars(
            select(ReviewAssignment).where(
                ReviewAssignment.review_case_id == assignment.review_case_id,
                ReviewAssignment.lane.in_((ReviewLane.PRIMARY, ReviewLane.SECONDARY)),
            )
        ).all()
        if len(independent) == 2 and all(
            item.status is ReviewStatus.COMPLETED for item in independent
        ):
            existing = session.scalar(
                select(ReviewAssignment.id).where(
                    ReviewAssignment.review_case_id == assignment.review_case_id,
                    ReviewAssignment.lane == ReviewLane.ADJUDICATION,
                )
            )
            if existing is None:
                session.add(
                    ReviewAssignment(
                        review_case_id=assignment.review_case_id,
                        lane=ReviewLane.ADJUDICATION,
                        status=ReviewStatus.PENDING,
                    )
                )
                session.flush()
    return assignment
