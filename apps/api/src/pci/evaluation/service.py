import json
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.claims.enums import ContributionField
from pci.contributions.repository import curator_actor_keys
from pci.contributions.service import latest_field_decisions
from pci.evaluation.schemas import (
    AgreementMetrics,
    ExtractionMetrics,
    FieldAgreementMetrics,
    FieldExtractionMetrics,
    GovernanceMetrics,
)
from pci.models.claims import CandidateClaim
from pci.models.contributions import ContributionGrounding, ContributionVersion, FieldDecisionAction
from pci.models.publication import PublicationAction, PublicationDecision, PublishedContribution
from pci.models.review import ReviewAssignment, ReviewCase, ReviewLane, ReviewStatus, SampleSplit


def _rate(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator else None


def safe_csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _cases(
    session: Session, run_id: uuid.UUID, split: SampleSplit | None = None
) -> list[ReviewCase]:
    query = select(ReviewCase).where(ReviewCase.sampling_run_id == run_id)
    if split is not None:
        query = query.where(ReviewCase.split == split)
    return list(session.scalars(query.order_by(ReviewCase.selection_order)).all())


def _reference_assignment(case: ReviewCase) -> ReviewAssignment | None:
    completed = [item for item in case.assignments if item.status is ReviewStatus.COMPLETED]
    for lane in (ReviewLane.ADJUDICATION, ReviewLane.SINGLE):
        if assignment := next((item for item in completed if item.lane is lane), None):
            return assignment
    return None


def _case_candidate_ids(case: ReviewCase) -> list[uuid.UUID]:
    if case.candidate_ids:
        return [uuid.UUID(item) for item in case.candidate_ids]
    return [case.candidate_contribution_id] if case.candidate_contribution_id else []


def _empty_extraction_counts() -> dict[ContributionField, dict[str, int]]:
    return {field: defaultdict(int) for field in ContributionField}


def _extraction_metrics_from_counts(
    counts: dict[ContributionField, dict[str, int]],
) -> dict[str, FieldExtractionMetrics]:
    result: dict[str, FieldExtractionMetrics] = {}
    for field, item in counts.items():
        precision = _rate(item["tp"], item["tp"] + item["fp"])
        recall = _rate(item["tp"], item["tp"] + item["fn"])
        f1 = (
            None
            if precision is None or recall is None or precision + recall == 0
            else 2 * precision * recall / (precision + recall)
        )
        result[field.value] = FieldExtractionMetrics(
            item["predicted"],
            item["reference"],
            item["tp"],
            item["fp"],
            item["fn"],
            precision,
            recall,
            f1,
            _rate(item["unsupported"], item["predicted"]),
            _rate(item["corrected"], item["reference"]),
            _rate(item["accepted"], item["reference"]),
            _rate(item["grounded"], item["reference"]),
        )
    return result


def compute_extraction_metrics(
    session: Session, sampling_run_id: uuid.UUID, split: SampleSplit
) -> ExtractionMetrics:
    cases = _cases(session, sampling_run_id, split)
    counts = _empty_extraction_counts()
    stratum_counts: dict[str, dict[ContributionField, dict[str, int]]] = {}
    evaluated_case_ids: set[uuid.UUID] = set()
    for case in cases:
        assignment = _reference_assignment(case)
        if assignment is None:
            continue
        evaluated_case_ids.add(case.id)
        candidate_ids = _case_candidate_ids(case)
        predicted = set(
            session.scalars(
                select(CandidateClaim.field).where(
                    CandidateClaim.candidate_contribution_id.in_(candidate_ids)
                )
            ).all()
        )
        decisions = latest_field_decisions(session, assignment.id)
        stratum_key = json.dumps(case.stratum, ensure_ascii=False, sort_keys=True)
        per_stratum = stratum_counts.setdefault(stratum_key, _empty_extraction_counts())
        for field in ContributionField:
            decision = decisions.get(field)
            reference = decision is not None and decision.action in {
                FieldDecisionAction.ACCEPT,
                FieldDecisionAction.CORRECT,
            }
            prediction = field in predicted
            for item in (counts[field], per_stratum[field]):
                item["predicted"] += int(prediction)
                item["reference"] += int(reference)
                item["tp"] += int(prediction and reference)
                item["fp"] += int(prediction and not reference)
                item["fn"] += int(not prediction and reference)
                item["unsupported"] += int(
                    prediction
                    and decision is not None
                    and decision.action
                    in {FieldDecisionAction.REJECT, FieldDecisionAction.INSUFFICIENT}
                )
                item["corrected"] += int(
                    decision is not None and decision.action is FieldDecisionAction.CORRECT
                )
                item["accepted"] += int(
                    decision is not None and decision.action is FieldDecisionAction.ACCEPT
                )
                item["grounded"] += int(reference and bool(decision and decision.grounding_ids))
    return ExtractionMetrics(
        sampling_run_id,
        split,
        evaluated_case_ids,
        _extraction_metrics_from_counts(counts),
        {
            stratum: _extraction_metrics_from_counts(stratum_values)
            for stratum, stratum_values in stratum_counts.items()
        },
    )


def compute_inter_rater_agreement(session: Session, sampling_run_id: uuid.UUID) -> AgreementMetrics:
    totals: dict[ContributionField, list[int]] = {field: [0, 0] for field in ContributionField}
    for case in _cases(session, sampling_run_id):
        primary = next(
            (
                item
                for item in case.assignments
                if item.lane is ReviewLane.PRIMARY and item.status is ReviewStatus.COMPLETED
            ),
            None,
        )
        secondary = next(
            (
                item
                for item in case.assignments
                if item.lane is ReviewLane.SECONDARY and item.status is ReviewStatus.COMPLETED
            ),
            None,
        )
        if primary is None or secondary is None:
            continue
        left, right = (
            latest_field_decisions(session, primary.id),
            latest_field_decisions(session, secondary.id),
        )
        for field in ContributionField:
            if field not in left or field not in right:
                continue
            totals[field][0] += 1
            left_value = (left[field].action, left[field].value)
            right_value = (right[field].action, right[field].value)
            totals[field][1] += int(left_value == right_value)
    return AgreementMetrics(
        sampling_run_id,
        {
            field.value: FieldAgreementMetrics(compared, agreed, _rate(agreed, compared))
            for field, (compared, agreed) in totals.items()
        },
    )


def _mean_seconds(pairs: list[tuple[datetime, datetime]]) -> float | None:
    return _rate(sum((end - start).total_seconds() for start, end in pairs), len(pairs))


def compute_governance_metrics(session: Session, sampling_run_id: uuid.UUID) -> GovernanceMetrics:
    cases = _cases(session, sampling_run_id)
    case_ids = [case.id for case in cases]
    assignments = [assignment for case in cases for assignment in case.assignments]
    review_pairs = [
        (item.started_at, item.completed_at)
        for item in assignments
        if item.started_at and item.completed_at
    ]
    versions = (
        list(
            session.scalars(
                select(ContributionVersion).where(ContributionVersion.review_case_id.in_(case_ids))
            ).all()
        )
        if case_ids
        else []
    )
    version_ids = [item.id for item in versions]
    decisions = (
        list(
            session.scalars(
                select(PublicationDecision).where(
                    PublicationDecision.contribution_version_id.in_(version_ids)
                )
            ).all()
        )
        if version_ids
        else []
    )
    projections = (
        list(
            session.scalars(
                select(PublishedContribution).where(
                    PublishedContribution.contribution_version_id.in_(version_ids)
                )
            ).all()
        )
        if version_ids
        else []
    )
    publish_pairs = [
        (version.validated_at, projection.published_at)
        for version in versions
        for projection in projections
        if projection.contribution_version_id == version.id and version.validated_at
    ]
    groundings = (
        list(
            session.scalars(
                select(ContributionGrounding).where(
                    ContributionGrounding.contribution_version_id.in_(version_ids)
                )
            ).all()
        )
        if version_ids
        else []
    )
    grounded_fields: dict[uuid.UUID, set[str]] = defaultdict(set)
    for grounding in groundings:
        grounded_fields[grounding.contribution_version_id].add(grounding.field.value)
    scientific_field_names = {field.value for field in ContributionField}
    published_field_count = 0
    grounded_field_count = 0
    for projection in projections:
        published_fields = set(projection.scientific_values) & scientific_field_names
        published_field_count += len(published_fields)
        grounded_field_count += len(
            published_fields & grounded_fields[projection.contribution_version_id]
        )
    supervised = [
        item
        for item in decisions
        if item.action in {PublicationAction.PUBLISH, PublicationAction.SUPERSEDE}
    ]
    separated = sum(
        item.supervisor_actor_key not in curator_actor_keys(session, item.contribution_version_id)
        for item in supervised
    )
    revoked = [item for item in decisions if item.action is PublicationAction.REVOKE]
    invisible = sum(
        not any(
            projection.scientific_contribution_id
            == next(
                (
                    v.scientific_contribution_id
                    for v in versions
                    if v.id == item.contribution_version_id
                ),
                None,
            )
            and projection.active
            for projection in projections
        )
        for item in revoked
    )
    return GovernanceMetrics(
        sampling_run_id,
        _mean_seconds(review_pairs),
        _rate(sum(item.action is PublicationAction.RETURN for item in decisions), len(decisions)),
        _mean_seconds(publish_pairs),
        _rate(grounded_field_count, published_field_count),
        _rate(separated, len(supervised)),
        _rate(invisible, len(revoked)),
    )
