import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pci.auth.contracts import AuthPrincipal
from pci.claims.enums import ContributionField
from pci.models.base import utc_now
from pci.models.claims import (
    CandidateClaim,
    CandidateContribution,
    CandidateGrounding,
    ExtractionRun,
)
from pci.models.contributions import (
    ContributionCandidateSource,
    ContributionGrounding,
    ContributionVersion,
    ContributionVersionStatus,
    FieldDecisionAction,
    ReviewFieldDecision,
    ScientificContribution,
)
from pci.models.documents import DocumentTextVersion
from pci.models.production import ProductionVersion
from pci.models.provenance import AuditEvent
from pci.models.review import (
    ReviewAssignment,
    ReviewCase,
    ReviewCaseKind,
    ReviewLane,
    ReviewStatus,
    SampleSplit,
    SamplingRun,
)


class IncompleteReviewError(ValueError):
    def __init__(self, missing_fields: tuple[ContributionField, ...]) -> None:
        self.missing_fields = missing_fields
        super().__init__("every governed field requires a decision")


class MissingGroundingError(ValueError):
    pass


class ImmutableContributionError(RuntimeError):
    pass


def governed_fields() -> tuple[ContributionField, ...]:
    return tuple(ContributionField)


def record_field_decision(
    session: Session,
    assignment_id: uuid.UUID,
    field: ContributionField,
    action: FieldDecisionAction,
    value: str | None,
    grounding_ids: Sequence[uuid.UUID],
    reason: str | None,
    principal: AuthPrincipal,
) -> ReviewFieldDecision:
    assignment = session.get(ReviewAssignment, assignment_id)
    if assignment is None or assignment.actor_key != principal.actor_key:
        raise ValueError("assignment not found")
    if assignment.status not in {ReviewStatus.ASSIGNED, ReviewStatus.IN_REVIEW}:
        raise ValueError("assignment is not active")
    review_case = session.get(ReviewCase, assignment.review_case_id)
    if review_case is None:
        raise ValueError("review case not found")
    if review_case.kind is ReviewCaseKind.SOURCE_REVALIDATION:
        raise ValueError("source revalidation is a supervision workflow")
    normalized_reason = reason.strip() if reason else None
    normalized_value = value.strip() if value else None
    if action is FieldDecisionAction.CORRECT and (
        normalized_value is None or not grounding_ids or normalized_reason is None
    ):
        raise MissingGroundingError("correction requires value, grounding, and reason")
    if action in {FieldDecisionAction.REJECT, FieldDecisionAction.INSUFFICIENT}:
        if normalized_reason is None:
            raise ValueError("negative decision requires a reason")
        normalized_value = None
        grounding_ids = ()
    grounded_claims = _grounded_claims_for_case(session, review_case, field, grounding_ids)
    if grounding_ids and len(grounded_claims) != len(set(grounding_ids)):
        raise MissingGroundingError("groundings must belong to this case, field, and source text")
    if action in {FieldDecisionAction.ACCEPT, FieldDecisionAction.CORRECT} and not grounding_ids:
        raise MissingGroundingError("accepted or corrected value requires grounding")
    if action is FieldDecisionAction.ACCEPT:
        candidate_values = {claim.value.strip() for claim in grounded_claims.values()}
        if review_case.kind is ReviewCaseKind.RETURN_CORRECTION:
            base = session.get(ContributionVersion, review_case.correction_base_version_id)
            if base is None:
                raise ValueError("correction base version not found")
            base_value = getattr(base, field.value)
            if base_value is not None:
                candidate_values.add(
                    base_value.value if hasattr(base_value, "value") else str(base_value)
                )
        if normalized_value is None and len(candidate_values) != 1:
            raise MissingGroundingError("accepted groundings must resolve to one candidate value")
        if normalized_value is None:
            normalized_value = candidate_values.pop()
        elif normalized_value not in candidate_values:
            raise MissingGroundingError("accepted value must equal the grounded candidate claim")
    latest = session.scalar(
        select(func.max(ReviewFieldDecision.sequence)).where(
            ReviewFieldDecision.review_assignment_id == assignment.id,
            ReviewFieldDecision.field == field,
        )
    )
    decision = ReviewFieldDecision(
        review_assignment_id=assignment.id,
        field=field,
        sequence=(latest or 0) + 1,
        action=action,
        value=normalized_value,
        grounding_ids=[str(item) for item in grounding_ids] or None,
        reason=normalized_reason,
        actor_key=principal.actor_key,
    )
    assignment.status = ReviewStatus.IN_REVIEW
    assignment.started_at = assignment.started_at or utc_now()
    session.add(decision)
    session.flush()
    return decision


def _grounded_claims_for_case(
    session: Session,
    review_case: ReviewCase,
    field: ContributionField,
    grounding_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, CandidateClaim]:
    if not grounding_ids:
        return {}
    candidate_ids = _case_candidate_ids(review_case)
    rows = session.execute(
        select(CandidateGrounding.id, CandidateClaim)
        .join(CandidateClaim, CandidateGrounding.candidate_claim_id == CandidateClaim.id)
        .join(
            CandidateContribution,
            CandidateClaim.candidate_contribution_id == CandidateContribution.id,
        )
        .join(ExtractionRun, CandidateContribution.extraction_run_id == ExtractionRun.id)
        .where(
            CandidateGrounding.id.in_(grounding_ids),
            CandidateClaim.candidate_contribution_id.in_(candidate_ids),
            CandidateClaim.field == field,
            CandidateGrounding.document_text_version_id == ExtractionRun.document_text_version_id,
        )
    ).all()
    return {grounding_id: claim for grounding_id, claim in rows}


def latest_field_decisions(
    session: Session, assignment_id: uuid.UUID
) -> dict[ContributionField, ReviewFieldDecision]:
    decisions = session.scalars(
        select(ReviewFieldDecision)
        .where(ReviewFieldDecision.review_assignment_id == assignment_id)
        .order_by(ReviewFieldDecision.field, ReviewFieldDecision.sequence.desc())
    ).all()
    latest: dict[ContributionField, ReviewFieldDecision] = {}
    for decision in decisions:
        latest.setdefault(decision.field, decision)
    return latest


def assert_review_complete(session: Session, assignment_id: uuid.UUID) -> None:
    decided = latest_field_decisions(session, assignment_id)
    missing = tuple(field for field in governed_fields() if field not in decided)
    if missing:
        raise IncompleteReviewError(missing)


def materialize_validated_contribution(
    session: Session, review_case_id: uuid.UUID, principal: AuthPrincipal
) -> ContributionVersion:
    review_case = session.get(ReviewCase, review_case_id)
    if review_case is None or review_case.kind not in {
        ReviewCaseKind.CANDIDATE,
        ReviewCaseKind.RETURN_CORRECTION,
    }:
        raise ValueError("candidate review case not found")
    existing = session.scalar(
        select(ContributionVersion).where(ContributionVersion.review_case_id == review_case_id)
    )
    if existing is not None and existing.status is not ContributionVersionStatus.DRAFT:
        return existing
    assignments = session.scalars(
        select(ReviewAssignment).where(ReviewAssignment.review_case_id == review_case_id)
    ).all()
    assignment = next(
        (
            item
            for item in assignments
            if item.status is ReviewStatus.COMPLETED
            and item.lane in {ReviewLane.SINGLE, ReviewLane.ADJUDICATION}
        ),
        None,
    )
    if assignment is None:
        raise IncompleteReviewError(governed_fields())
    decisions = latest_field_decisions(session, assignment.id)
    missing = tuple(field for field in governed_fields() if field not in decisions)
    if missing:
        raise IncompleteReviewError(missing)
    candidate_ids = _case_candidate_ids(review_case)
    production_id, source_text_version_id = _candidate_source_context(session, candidate_ids)
    values: dict[str, object | None] = {
        field.value: (
            decisions[field].value
            if decisions[field].action in {FieldDecisionAction.ACCEPT, FieldDecisionAction.CORRECT}
            else None
        )
        for field in governed_fields()
    }
    if value := values.get(ContributionField.CONTRIBUTION_TYPE.value):
        from pci.claims.enums import ContributionType

        values[ContributionField.CONTRIBUTION_TYPE.value] = ContributionType(str(value))
    if review_case.kind is ReviewCaseKind.RETURN_CORRECTION:
        if existing is None:
            raise ValueError("correction draft not found")
        version = existing
        contribution = session.scalar(
            select(ScientificContribution)
            .where(ScientificContribution.id == version.scientific_contribution_id)
            .with_for_update()
        )
        if contribution is None or contribution.production_id != production_id:
            raise ValueError("correction draft belongs to another production")
        for field_name, field_value in values.items():
            setattr(version, field_name, field_value)
        version.status = ContributionVersionStatus.VALIDATED
        version.validated_at = utc_now()
        audit_action = "contribution.revision_validated"
    else:
        contribution = ScientificContribution(production_id=production_id)
        session.add(contribution)
        session.flush()
        version = ContributionVersion(
            scientific_contribution_id=contribution.id,
            version=1,
            status=ContributionVersionStatus.VALIDATED,
            review_case_id=review_case.id,
            created_by=principal.actor_key,
            validated_at=utc_now(),
            **values,
        )
        session.add(version)
        session.flush()
        contribution.current_version_number = 1
        audit_action = "contribution.validated"
    completed_assignments = [
        item for item in assignments if item.status is ReviewStatus.COMPLETED and item.actor_key
    ]
    for candidate_id in candidate_ids:
        for source_assignment in completed_assignments:
            session.add(
                ContributionCandidateSource(
                    contribution_version_id=version.id,
                    candidate_contribution_id=candidate_id,
                    review_assignment_id=source_assignment.id,
                    curator_actor_key=source_assignment.actor_key or principal.actor_key,
                )
            )
    for field, decision in decisions.items():
        if decision.action not in {FieldDecisionAction.ACCEPT, FieldDecisionAction.CORRECT}:
            continue
        for grounding_id in decision.grounding_ids or []:
            grounding = session.get(CandidateGrounding, uuid.UUID(grounding_id))
            if grounding is None or grounding.document_text_version_id != source_text_version_id:
                raise MissingGroundingError(
                    "approved grounding must belong to the case source text"
                )
            text = session.get(DocumentTextVersion, grounding.document_text_version_id)
            if text is None:
                raise MissingGroundingError("approved grounding source text is missing")
            session.add(
                ContributionGrounding(
                    contribution_version_id=version.id,
                    field=field,
                    source_scope=text.scope.value,
                    document_text_version_id=text.id,
                    page_number=grounding.page_number,
                    section=grounding.section,
                    start_offset=grounding.start_offset,
                    end_offset=grounding.end_offset,
                    quote=grounding.quote,
                    quote_hash=grounding.quote_hash,
                )
            )
    session.add(
        AuditEvent(
            actor=principal.actor_key,
            action=audit_action,
            entity_type="ContributionVersion",
            entity_id=version.id,
            after={"status": ContributionVersionStatus.VALIDATED.value},
        )
    )
    session.flush()
    return version


def create_revision(
    session: Session,
    contribution_id: uuid.UUID,
    base_version_id: uuid.UUID,
    review_case_id: uuid.UUID,
    actor_key: str,
) -> ContributionVersion:
    contribution = session.scalar(
        select(ScientificContribution)
        .where(ScientificContribution.id == contribution_id)
        .with_for_update()
    )
    if contribution is None:
        raise ValueError("scientific contribution not found")
    base = session.get(ContributionVersion, base_version_id)
    if base is None or base.scientific_contribution_id != contribution_id:
        raise ValueError("base contribution version not found")
    if base.status is not ContributionVersionStatus.RETURNED:
        raise ValueError("only a returned version can open a correction")
    if base.version != contribution.current_version_number:
        raise ValueError("correction must start from the current version")
    values = {field.value: getattr(base, field.value) for field in governed_fields()}
    revision = ContributionVersion(
        scientific_contribution_id=contribution_id,
        version=contribution.current_version_number + 1,
        status=ContributionVersionStatus.DRAFT,
        review_case_id=review_case_id,
        base_version_id=base.id,
        created_by=actor_key,
        **values,
    )
    session.add(revision)
    session.flush()
    contribution.current_version_number = revision.version
    return revision


def open_return_correction(
    session: Session,
    returned_version: ContributionVersion,
    reason: str,
    actor_key: str,
) -> ContributionVersion:
    existing_case = session.scalar(
        select(ReviewCase).where(ReviewCase.correction_base_version_id == returned_version.id)
    )
    if existing_case is not None:
        existing_revision = session.scalar(
            select(ContributionVersion).where(
                ContributionVersion.review_case_id == existing_case.id
            )
        )
        if existing_revision is None:
            raise ValueError("correction case has no draft version")
        return existing_revision
    candidate_ids = list(
        dict.fromkeys(
            session.scalars(
                select(ContributionCandidateSource.candidate_contribution_id).where(
                    ContributionCandidateSource.contribution_version_id == returned_version.id
                )
            ).all()
        )
    )
    if not candidate_ids:
        raise ValueError("returned contribution has no candidate provenance")
    source_case = (
        session.get(ReviewCase, returned_version.review_case_id)
        if returned_version.review_case_id is not None
        else None
    )
    sampling_run = SamplingRun(
        target_size=1,
        selected_size=1,
        test_fraction="0",
        double_code_fraction="0",
        seed=f"return-correction:{returned_version.id}",
        rule_version="return-correction-v1",
    )
    session.add(sampling_run)
    session.flush()
    correction_case = ReviewCase(
        sampling_run_id=sampling_run.id,
        kind=ReviewCaseKind.RETURN_CORRECTION,
        candidate_contribution_id=candidate_ids[0],
        candidate_ids=[str(item) for item in candidate_ids],
        correction_base_version_id=returned_version.id,
        stratum=source_case.stratum if source_case is not None else {},
        split=SampleSplit.OPERATIONS,
        priority_reason=reason[:1000],
        selection_order=1,
    )
    session.add(correction_case)
    session.flush()
    revision = create_revision(
        session,
        returned_version.scientific_contribution_id,
        returned_version.id,
        correction_case.id,
        actor_key,
    )
    session.add(
        ReviewAssignment(
            review_case_id=correction_case.id,
            lane=ReviewLane.SINGLE,
            status=ReviewStatus.PENDING,
        )
    )
    session.add(
        AuditEvent(
            actor=actor_key,
            action="contribution.return_correction_opened",
            entity_type="ContributionVersion",
            entity_id=revision.id,
            after={
                "base_version_id": str(returned_version.id),
                "reason": reason,
                "status": ContributionVersionStatus.DRAFT.value,
            },
        )
    )
    session.flush()
    return revision


def split_review_case(
    session: Session,
    review_case_id: uuid.UUID,
    partitions: Sequence[Sequence[uuid.UUID]],
    principal: AuthPrincipal,
) -> tuple[ReviewCase, ...]:
    del principal
    source = session.get(ReviewCase, review_case_id)
    if (
        source is None
        or source.superseded_by_case_id is not None
        or any(not partition for partition in partitions)
    ):
        raise ValueError("review case or partitions are invalid")
    expected = set(_case_candidate_ids(source))
    supplied = [item for partition in partitions for item in partition]
    if set(supplied) != expected or len(supplied) != len(expected):
        raise ValueError("partitions must cover each candidate exactly once")
    created: list[ReviewCase] = []
    for offset, partition in enumerate(partitions, start=1):
        case = ReviewCase(
            sampling_run_id=source.sampling_run_id,
            kind=ReviewCaseKind.CANDIDATE,
            candidate_contribution_id=partition[0],
            candidate_ids=[str(item) for item in partition],
            stratum=source.stratum,
            split=source.split,
            priority_reason="curator_split",
            selection_order=source.selection_order * 100 + offset,
        )
        session.add(case)
        session.flush()
        session.add(
            ReviewAssignment(
                review_case_id=case.id,
                lane=ReviewLane.SINGLE,
                status=ReviewStatus.PENDING,
            )
        )
        created.append(case)
    _cancel_case_assignments(session, source.id)
    source.superseded_by_case_id = created[0].id
    session.flush()
    return tuple(created)


def merge_review_cases(
    session: Session,
    review_case_ids: Sequence[uuid.UUID],
    principal: AuthPrincipal,
) -> ReviewCase:
    del principal
    cases = [session.get(ReviewCase, item) for item in review_case_ids]
    if not cases or any(item is None for item in cases):
        raise ValueError("review case not found")
    typed_cases = [item for item in cases if item is not None]
    if any(item.superseded_by_case_id is not None for item in typed_cases):
        raise ValueError("superseded review cases cannot be merged")
    if len({item.sampling_run_id for item in typed_cases}) != 1:
        raise ValueError("review cases must belong to the same sampling run")
    if len({item.split for item in typed_cases}) != 1:
        raise ValueError("calibration and test cases cannot be merged")
    candidate_ids = [item for case in typed_cases for item in _case_candidate_ids(case)]
    _candidate_source_context(session, candidate_ids)
    first = typed_cases[0]
    merged = ReviewCase(
        sampling_run_id=first.sampling_run_id,
        kind=ReviewCaseKind.CANDIDATE,
        candidate_contribution_id=candidate_ids[0],
        candidate_ids=[str(item) for item in candidate_ids],
        stratum=first.stratum,
        split=first.split,
        priority_reason="curator_merge",
        selection_order=min(item.selection_order for item in typed_cases),
    )
    session.add(merged)
    session.flush()
    session.add(
        ReviewAssignment(
            review_case_id=merged.id,
            lane=ReviewLane.SINGLE,
            status=ReviewStatus.PENDING,
        )
    )
    for case in typed_cases:
        _cancel_case_assignments(session, case.id)
        case.superseded_by_case_id = merged.id
    session.flush()
    return merged


def _case_candidate_ids(review_case: ReviewCase) -> list[uuid.UUID]:
    if review_case.candidate_ids:
        return [uuid.UUID(item) for item in review_case.candidate_ids]
    if review_case.candidate_contribution_id is None:
        return []
    return [review_case.candidate_contribution_id]


def _candidate_source_context(
    session: Session, candidate_ids: Sequence[uuid.UUID]
) -> tuple[uuid.UUID, uuid.UUID]:
    unique_ids = list(dict.fromkeys(candidate_ids))
    rows = session.execute(
        select(
            CandidateContribution.id,
            DocumentTextVersion.id,
            ProductionVersion.production_id,
        )
        .join(ExtractionRun, ExtractionRun.document_text_version_id == DocumentTextVersion.id)
        .join(CandidateContribution, CandidateContribution.extraction_run_id == ExtractionRun.id)
        .join(
            ProductionVersion,
            ProductionVersion.id == DocumentTextVersion.production_version_id,
        )
        .where(CandidateContribution.id.in_(unique_ids))
    ).all()
    if len(rows) != len(unique_ids):
        raise ValueError("one or more candidates lack source context")
    production_ids = {production_id for _, _, production_id in rows}
    if len(production_ids) != 1:
        raise ValueError("all candidates must belong to the same production")
    text_version_ids = {text_version_id for _, text_version_id, _ in rows}
    if len(text_version_ids) != 1:
        raise ValueError("all candidates must share a single document text version")
    return production_ids.pop(), text_version_ids.pop()


def _cancel_case_assignments(session: Session, review_case_id: uuid.UUID) -> None:
    for assignment in session.scalars(
        select(ReviewAssignment).where(ReviewAssignment.review_case_id == review_case_id)
    ):
        if assignment.status is not ReviewStatus.COMPLETED:
            assignment.status = ReviewStatus.CANCELLED
