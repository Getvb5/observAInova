from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from pci.problems.dialogue import (
    FieldAnswer,
    NextQuestion,
    build_context,
    build_draft,
    build_summary,
    get_next_question,
    missing_fields,
    validate_answer,
)
from pci.problems.models import (
    KnowledgeStatus,
    ProblemContextVersion,
    ProblemField,
    ProblemStatus,
    PublicProblem,
)
from pci.problems.repository import (
    append_answer,
    create_problem,
    list_answer_events,
)

MapStatus = Literal["not_ready", "awaiting_validated_contributions"]


@dataclass(frozen=True)
class CreatedProblem:
    problem: PublicProblem
    edit_token: str


@dataclass(frozen=True)
class ProblemState:
    problem: PublicProblem
    answers: dict[ProblemField, FieldAnswer]
    next_question: NextQuestion | None
    missing_fields: tuple[ProblemField, ...]
    ready_to_confirm: bool
    structured_summary: str | None
    map_status: MapStatus


@dataclass(frozen=True)
class Confirmation:
    problem: PublicProblem
    version: ProblemContextVersion
    map_status: Literal["awaiting_validated_contributions"]


class ProblemStateConflict(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def create_public_problem(session: Session, description: str) -> CreatedProblem:
    problem, edit_token = create_problem(session, description)
    return CreatedProblem(problem=problem, edit_token=edit_token)


def get_problem_state(session: Session, problem: PublicProblem) -> ProblemState:
    draft = build_draft(problem.description, list_answer_events(session, problem.id))
    missing = missing_fields(draft)
    ready = not missing
    summary = build_summary(draft) if ready else None
    map_status: MapStatus = (
        "awaiting_validated_contributions"
        if problem.status is ProblemStatus.CONFIRMED
        else "not_ready"
    )
    return ProblemState(
        problem=problem,
        answers=dict(draft.answers),
        next_question=get_next_question(draft),
        missing_fields=missing,
        ready_to_confirm=ready,
        structured_summary=summary,
        map_status=map_status,
    )


def record_answer(
    session: Session,
    problem: PublicProblem,
    field: ProblemField,
    value: str | None,
    knowledge_status: KnowledgeStatus,
) -> ProblemState:
    if problem.status is ProblemStatus.CONFIRMED:
        raise ProblemStateConflict("reopen_before_answering")
    answer = validate_answer(field, value, knowledge_status)
    append_answer(session, problem, field, answer.value, answer.knowledge_status)
    return get_problem_state(session, problem)


def confirm_public_problem(session: Session, problem: PublicProblem) -> Confirmation:
    if problem.status is ProblemStatus.CONFIRMED:
        raise ProblemStateConflict("already_confirmed")
    draft = build_draft(problem.description, list_answer_events(session, problem.id))
    context = build_context(draft)
    summary = build_summary(draft)
    version_number = problem.current_version_number + 1
    version = ProblemContextVersion(
        problem_id=problem.id,
        version=version_number,
        context=context,
        structured_summary=summary,
    )
    session.add(version)
    problem.current_version_number = version_number
    problem.status = ProblemStatus.CONFIRMED
    session.flush()
    return Confirmation(
        problem=problem,
        version=version,
        map_status="awaiting_validated_contributions",
    )


def reopen_problem(session: Session, problem: PublicProblem) -> ProblemState:
    if problem.status is ProblemStatus.CONFIRMED:
        problem.status = ProblemStatus.DRAFT
        session.flush()
    return get_problem_state(session, problem)
