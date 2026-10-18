import hashlib
import uuid
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from pci.models.review import (
    ReviewAssignment,
    ReviewCase,
    ReviewCaseKind,
    ReviewLane,
    ReviewStatus,
    SampleSplit,
    SamplingRun,
)
from pci.review.repository import CandidateSamplingData, candidate_sampling_data


@dataclass(frozen=True, slots=True)
class SamplingConfig:
    target_size: int
    test_fraction: Decimal
    double_code_fraction: Decimal
    seed: str
    rule_version: str

    def __post_init__(self) -> None:
        if self.target_size < 1:
            raise ValueError("target_size must be positive")
        if not Decimal(0) <= self.test_fraction <= Decimal(1):
            raise ValueError("test_fraction must be between zero and one")
        if not Decimal(0) <= self.double_code_fraction <= Decimal(1):
            raise ValueError("double_code_fraction must be between zero and one")
        if not self.seed or not self.rule_version:
            raise ValueError("seed and rule_version are required")


def create_stratified_sample(
    session: Session,
    candidate_ids: Sequence[uuid.UUID],
    config: SamplingConfig,
) -> SamplingRun:
    unique_ids = list(dict.fromkeys(candidate_ids))
    data = candidate_sampling_data(session, unique_ids)
    if len(data) != len(unique_ids):
        raise ValueError("one or more candidates do not exist or lack source context")
    selected = _round_robin_selection(data, config.seed, config.target_size)
    selected_size = len(selected)
    test_count = _fraction_count(selected_size, config.test_fraction)
    double_count = _fraction_count(selected_size, config.double_code_fraction)
    sampling_run = SamplingRun(
        target_size=config.target_size,
        selected_size=selected_size,
        test_fraction=str(config.test_fraction),
        double_code_fraction=str(config.double_code_fraction),
        seed=config.seed,
        rule_version=config.rule_version,
    )
    session.add(sampling_run)
    session.flush()
    for index, item in enumerate(selected, start=1):
        review_case = ReviewCase(
            sampling_run_id=sampling_run.id,
            kind=ReviewCaseKind.CANDIDATE,
            candidate_contribution_id=item.candidate_id,
            candidate_ids=[str(item.candidate_id)],
            stratum=_stratum(item),
            split=SampleSplit.TEST if index <= test_count else SampleSplit.CALIBRATION,
            priority_reason="stratified_representative_sample",
            selection_order=index,
        )
        session.add(review_case)
        session.flush()
        lanes = (
            (ReviewLane.PRIMARY, ReviewLane.SECONDARY)
            if index <= double_count
            else (ReviewLane.SINGLE,)
        )
        session.add_all(
            [
                ReviewAssignment(
                    review_case_id=review_case.id,
                    lane=lane,
                    status=ReviewStatus.PENDING,
                )
                for lane in lanes
            ]
        )
    session.flush()
    session.refresh(sampling_run)
    return sampling_run


def _round_robin_selection(
    candidates: list[CandidateSamplingData], seed: str, target_size: int
) -> list[CandidateSamplingData]:
    grouped: dict[tuple[object, ...], list[CandidateSamplingData]] = defaultdict(list)
    for candidate in candidates:
        grouped[_stratum_key(candidate)].append(candidate)
    queues: dict[tuple[object, ...], deque[CandidateSamplingData]] = {}
    for key, values in grouped.items():
        values.sort(key=lambda item: _seeded_digest(seed, item.candidate_id))
        queues[key] = deque(values)
    selected: list[CandidateSamplingData] = []
    ordered_keys = sorted(queues, key=lambda key: tuple(str(item) for item in key))
    while len(selected) < min(target_size, len(candidates)):
        progressed = False
        for key in ordered_keys:
            if queues[key] and len(selected) < target_size:
                selected.append(queues[key].popleft())
                progressed = True
        if not progressed:
            break
    return selected


def _stratum(candidate: CandidateSamplingData) -> dict[str, object]:
    return {
        "institution": candidate.institution,
        "knowledge_area": candidate.knowledge_area,
        "publication_year": candidate.publication_year,
        "production_type": candidate.production_type.value if candidate.production_type else None,
        "text_scope": candidate.text_scope.value,
        "contribution_type": (
            candidate.contribution_type.value if candidate.contribution_type else "not_informed"
        ),
    }


def _stratum_key(candidate: CandidateSamplingData) -> tuple[object, ...]:
    return tuple(_stratum(candidate).values())


def _seeded_digest(seed: str, candidate_id: uuid.UUID) -> str:
    return hashlib.sha256(f"{seed}{candidate_id}".encode()).hexdigest()


def _fraction_count(size: int, fraction: Decimal) -> int:
    return min(size, int(Decimal(size) * fraction + Decimal("0.5")))
