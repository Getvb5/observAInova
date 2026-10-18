import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pci.problems.models import (
    KnowledgeStatus,
    ProblemAnswerEvent,
    ProblemContextVersion,
    ProblemField,
    ProblemStatus,
    ProblemVisibility,
    PublicProblem,
)


def test_problem_field_values_are_stable() -> None:
    assert [item.value for item in ProblemField] == [
        "territory",
        "affected_population_or_service",
        "observed_consequences",
        "perceived_causes",
        "attempted_actions",
        "available_resources",
        "constraints",
        "desired_outcome",
    ]


def test_problem_starts_private_and_draft(session: Session) -> None:
    problem = PublicProblem(description="Demora no atendimento", edit_token_digest="a" * 64)
    session.add(problem)
    session.flush()

    assert problem.status is ProblemStatus.DRAFT
    assert problem.visibility is ProblemVisibility.PRIVATE
    assert problem.current_version_number == 0
    assert problem.next_event_sequence == 1


def test_answer_event_is_append_only(session: Session) -> None:
    problem = PublicProblem(description="Demora no atendimento", edit_token_digest="a" * 64)
    session.add(problem)
    session.flush()
    event = ProblemAnswerEvent(
        problem_id=problem.id,
        sequence=1,
        field=ProblemField.TERRITORY,
        value="Caruaru",
        knowledge_status=KnowledgeStatus.REPORTED_FACT,
    )
    session.add(event)
    session.commit()

    event.value = "Recife"
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()


def test_context_version_is_append_only(session: Session) -> None:
    problem = PublicProblem(description="Demora no atendimento", edit_token_digest="b" * 64)
    context_version = ProblemContextVersion(
        problem=problem,
        version=1,
        structured_summary="Resumo",
        context={"territory": {"value": None, "knowledge_status": "unknown"}},
    )
    session.add(context_version)
    session.commit()

    context_version.structured_summary = "Resumo sobrescrito"
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()


def test_context_version_is_unique_per_problem_and_number(session: Session) -> None:
    problem = PublicProblem(description="Demora no atendimento", edit_token_digest="b" * 64)
    session.add(problem)
    session.flush()
    context = {"territory": {"value": None, "knowledge_status": "unknown"}}
    session.add_all(
        [
            ProblemContextVersion(
                problem_id=problem.id,
                version=1,
                structured_summary="Resumo",
                context=context,
            ),
            ProblemContextVersion(
                problem_id=problem.id,
                version=1,
                structured_summary="Outro",
                context=context,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()
