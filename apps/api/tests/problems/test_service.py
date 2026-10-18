import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.problems.dialogue import FIELD_ORDER, IncompleteProblemError
from pci.problems.models import (
    KnowledgeStatus,
    ProblemContextVersion,
    ProblemField,
    ProblemStatus,
    PublicProblem,
)
from pci.problems.service import (
    CreatedProblem,
    ProblemStateConflict,
    confirm_public_problem,
    create_public_problem,
    get_problem_state,
    record_answer,
    reopen_problem,
)


def answer_all_fields(
    session: Session, problem: PublicProblem, *, unknown_optional: bool
) -> None:
    for field in FIELD_ORDER:
        if unknown_optional and field not in {
            ProblemField.AFFECTED_POPULATION_OR_SERVICE,
            ProblemField.DESIRED_OUTCOME,
        }:
            record_answer(session, problem, field, None, KnowledgeStatus.UNKNOWN)
            continue
        status = (
            KnowledgeStatus.PERCEPTION
            if field is ProblemField.PERCEIVED_CAUSES
            else KnowledgeStatus.REPORTED_FACT
        )
        record_answer(
            session,
            problem,
            field,
            f"resposta para {field.value}",
            status,
        )


def create_and_confirm_complete_problem(session: Session) -> CreatedProblem:
    created = create_public_problem(session, "A fila para consultas está aumentando")
    answer_all_fields(session, created.problem, unknown_optional=False)
    confirm_public_problem(session, created.problem)
    return created


def test_confirm_creates_immutable_version_and_updates_problem(session: Session) -> None:
    created = create_public_problem(session, "A fila para consultas está aumentando")
    answer_all_fields(session, created.problem, unknown_optional=True)

    result = confirm_public_problem(session, created.problem)

    assert result.version.version == 1
    assert result.problem.status is ProblemStatus.CONFIRMED
    assert result.problem.current_version_number == 1
    assert result.map_status == "awaiting_validated_contributions"
    assert result.version.context["territory"] == {
        "value": None,
        "knowledge_status": "unknown",
    }


def test_incomplete_confirmation_does_not_create_version(session: Session) -> None:
    created = create_public_problem(session, "A fila para consultas está aumentando")

    with pytest.raises(IncompleteProblemError) as error:
        confirm_public_problem(session, created.problem)

    assert error.value.missing_fields == FIELD_ORDER
    assert session.query(ProblemContextVersion).count() == 0
    assert created.problem.status is ProblemStatus.DRAFT


def test_revision_reuses_latest_answers_and_creates_version_two(session: Session) -> None:
    created = create_and_confirm_complete_problem(session)
    first_version = session.scalar(
        select(ProblemContextVersion).where(ProblemContextVersion.version == 1)
    )
    assert first_version is not None
    first_constraints = first_version.context["constraints"]["value"]
    reopen_problem(session, created.problem)
    record_answer(
        session,
        created.problem,
        ProblemField.CONSTRAINTS,
        "Sem aumento de equipe",
        KnowledgeStatus.REPORTED_FACT,
    )

    result = confirm_public_problem(session, created.problem)

    assert result.version.version == 2
    assert result.version.context["constraints"]["value"] == "Sem aumento de equipe"
    assert first_version.context["constraints"]["value"] == first_constraints


def test_confirmed_problem_must_be_reopened_before_answering(session: Session) -> None:
    created = create_and_confirm_complete_problem(session)

    with pytest.raises(ProblemStateConflict, match="reopen_before_answering"):
        record_answer(
            session,
            created.problem,
            ProblemField.CONSTRAINTS,
            "Sem aumento de equipe",
            KnowledgeStatus.REPORTED_FACT,
        )


def test_complete_draft_exposes_exact_review_summary(session: Session) -> None:
    created = create_public_problem(session, "A fila para consultas está aumentando")
    answer_all_fields(session, created.problem, unknown_optional=False)

    state = get_problem_state(session, created.problem)

    assert state.ready_to_confirm is True
    assert state.next_question is None
    assert state.structured_summary is not None
    assert "resposta para desired_outcome" in state.structured_summary
    assert state.map_status == "not_ready"
