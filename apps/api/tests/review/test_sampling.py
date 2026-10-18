from decimal import Decimal

from sqlalchemy.orm import Session

from pci.models.documents import DocumentTextScope
from pci.models.enums import ProductionType
from pci.review.sampling import SamplingConfig, create_stratified_sample

from .conftest import CandidateFactory


def case_signature(case: object) -> tuple[tuple[str, object], ...]:
    return tuple(sorted(case.stratum.items()))  # type: ignore[attr-defined,no-any-return]


def test_stratified_sample_covers_each_available_stratum_before_refill(
    session: Session, candidate_factory: CandidateFactory
) -> None:
    candidates = [
        candidate_factory(institution="UFPE", knowledge_area="Saúde", year=2024),
        candidate_factory(institution="UFPE", knowledge_area="Saúde", year=2023),
        candidate_factory(institution="IFPE", knowledge_area="Engenharias", year=2024),
        candidate_factory(
            institution="UFRPE",
            knowledge_area="Agrárias",
            production_type=ProductionType.DISSERTATION,
        ),
        candidate_factory(
            institution="UPE", scope=DocumentTextScope.ABSTRACT_ONLY
        ),
    ]

    run = create_stratified_sample(
        session,
        [candidate.id for candidate in candidates],
        SamplingConfig(5, Decimal("0.20"), Decimal("0.20"), "thesis-seed", "v1"),
    )

    assert len(run.cases) == 5
    assert len({case_signature(case) for case in run.cases}) == 5


def test_missing_area_is_preserved_as_not_informed_stratum(
    session: Session, candidate_factory: CandidateFactory
) -> None:
    candidate = candidate_factory(knowledge_area=None)

    run = create_stratified_sample(
        session,
        [candidate.id],
        SamplingConfig(1, Decimal(0), Decimal(0), "seed", "v1"),
    )

    assert run.cases[0].stratum["knowledge_area"] == "not_informed"


def test_same_seed_produces_same_candidate_order(
    session: Session, candidate_factory: CandidateFactory
) -> None:
    candidates = [candidate_factory(year=2020 + index) for index in range(5)]
    config = SamplingConfig(4, Decimal("0.25"), Decimal("0.25"), "fixed", "v1")

    first = create_stratified_sample(session, [item.id for item in candidates], config)
    second = create_stratified_sample(session, [item.id for item in candidates], config)

    assert [case.candidate_contribution_id for case in first.cases] == [
        case.candidate_contribution_id for case in second.cases
    ]
