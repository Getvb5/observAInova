import uuid

from sqlalchemy.orm import Session

from pci.problems.models import KnowledgeStatus, ProblemField
from pci.problems.repository import (
    append_answer,
    create_problem,
    get_authorized_problem,
    latest_answers,
    list_answer_events,
)
from pci.problems.security import digest_edit_token


def test_create_problem_returns_token_but_stores_only_digest(session: Session) -> None:
    problem, token = create_problem(session, "  A fila para consultas está aumentando  ")
    session.flush()

    assert len(token) >= 43
    assert problem.description == "A fila para consultas está aumentando"
    assert problem.edit_token_digest == digest_edit_token(token)
    assert token not in str(problem.__dict__)


def test_wrong_token_and_unknown_id_are_both_unauthorized(session: Session) -> None:
    problem, token = create_problem(session, "A fila para consultas está aumentando")
    session.flush()

    assert get_authorized_problem(session, problem.id, token) is problem
    assert get_authorized_problem(session, problem.id, "wrong") is None
    assert get_authorized_problem(session, uuid.uuid4(), token) is None


def test_correction_preserves_history_and_latest_answer_wins(session: Session) -> None:
    problem, _ = create_problem(session, "A fila para consultas está aumentando")
    append_answer(
        session,
        problem,
        ProblemField.TERRITORY,
        "Recife",
        KnowledgeStatus.REPORTED_FACT,
    )
    append_answer(
        session,
        problem,
        ProblemField.TERRITORY,
        "Caruaru",
        KnowledgeStatus.REPORTED_FACT,
    )
    session.flush()

    assert [event.value for event in list_answer_events(session, problem.id)] == [
        "Recife",
        "Caruaru",
    ]
    assert [event.sequence for event in list_answer_events(session, problem.id)] == [1, 2]
    assert latest_answers(session, problem.id)[ProblemField.TERRITORY].value == "Caruaru"
    assert problem.next_event_sequence == 3
