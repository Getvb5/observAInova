import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.problems.models import (
    KnowledgeStatus,
    ProblemAnswerEvent,
    ProblemField,
    PublicProblem,
)
from pci.problems.security import digest_edit_token, generate_edit_token, token_matches


def create_problem(session: Session, description: str) -> tuple[PublicProblem, str]:
    token = generate_edit_token()
    problem = PublicProblem(
        description=description.strip(),
        edit_token_digest=digest_edit_token(token),
    )
    session.add(problem)
    session.flush()
    return problem, token


def get_authorized_problem(
    session: Session, problem_id: uuid.UUID, token: str
) -> PublicProblem | None:
    problem = session.get(PublicProblem, problem_id)
    if problem is None or not token_matches(token, problem.edit_token_digest):
        return None
    return problem


def append_answer(
    session: Session,
    problem: PublicProblem,
    field: ProblemField,
    value: str | None,
    knowledge_status: KnowledgeStatus,
) -> ProblemAnswerEvent:
    locked_problem = session.scalar(
        select(PublicProblem)
        .where(PublicProblem.id == problem.id)
        .with_for_update()
    )
    if locked_problem is None:
        raise LookupError("Problem not found")

    sequence = locked_problem.next_event_sequence
    locked_problem.next_event_sequence = sequence + 1
    event = ProblemAnswerEvent(
        problem_id=locked_problem.id,
        sequence=sequence,
        field=field,
        value=value,
        knowledge_status=knowledge_status,
    )
    session.add(event)
    session.flush()
    return event


def list_answer_events(
    session: Session, problem_id: uuid.UUID
) -> tuple[ProblemAnswerEvent, ...]:
    events = session.scalars(
        select(ProblemAnswerEvent)
        .where(ProblemAnswerEvent.problem_id == problem_id)
        .order_by(ProblemAnswerEvent.sequence)
    )
    return tuple(events)


def latest_answers(
    session: Session, problem_id: uuid.UUID
) -> dict[ProblemField, ProblemAnswerEvent]:
    latest: dict[ProblemField, ProblemAnswerEvent] = {}
    for event in list_answer_events(session, problem_id):
        latest[event.field] = event
    return latest
