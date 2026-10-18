import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from pci.api_dependencies import SessionDependency
from pci.problems import repository
from pci.problems.dialogue import FIELD_ORDER, IncompleteProblemError
from pci.problems.models import PublicProblem
from pci.problems.schemas import (
    AnswerProblemRequest,
    ConfirmedProblemResponse,
    CreatedProblemResponse,
    CreateProblemRequest,
    NextQuestionResponse,
    ProblemFieldResponse,
    ProblemStateResponse,
)
from pci.problems.service import (
    ProblemState,
    ProblemStateConflict,
    confirm_public_problem,
    create_public_problem,
    get_problem_state,
    record_answer,
    reopen_problem,
)

router = APIRouter(prefix="/problems", tags=["problems"])
ProblemToken = Annotated[str, Header(alias="X-Problem-Token")]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Problem not found",
    )


def _authorized_problem(
    session: SessionDependency,
    problem_id: uuid.UUID,
    token: str,
) -> PublicProblem:
    problem = repository.get_authorized_problem(session, problem_id, token)
    if problem is None:
        raise _not_found()
    return problem


def _state_response(state: ProblemState) -> ProblemStateResponse:
    fields = {
        field: (
            ProblemFieldResponse(
                value=state.answers[field].value,
                knowledge_status=state.answers[field].knowledge_status,
            )
            if field in state.answers
            else None
        )
        for field in FIELD_ORDER
    }
    next_question = (
        NextQuestionResponse(
            field=state.next_question.field,
            prompt=state.next_question.prompt,
            accepts_unknown=state.next_question.accepts_unknown,
        )
        if state.next_question is not None
        else None
    )
    return ProblemStateResponse(
        problem_id=state.problem.id,
        status=state.problem.status,
        description=state.problem.description,
        fields=fields,
        next_question=next_question,
        missing_fields=list(state.missing_fields),
        ready_to_confirm=state.ready_to_confirm,
        current_version=state.problem.current_version_number,
        structured_summary=state.structured_summary,
        map_status=state.map_status,
    )


@router.post("", response_model=CreatedProblemResponse, status_code=status.HTTP_201_CREATED)
def create_problem(
    request: CreateProblemRequest,
    session: SessionDependency,
) -> CreatedProblemResponse:
    created = create_public_problem(session, request.description)
    state = get_problem_state(session, created.problem)
    return CreatedProblemResponse(
        problem_id=created.problem.id,
        edit_token=created.edit_token,
        state=_state_response(state),
    )


@router.get("/{problem_id}", response_model=ProblemStateResponse)
def read_problem(
    problem_id: uuid.UUID,
    session: SessionDependency,
    problem_token: ProblemToken = "",
) -> ProblemStateResponse:
    problem = _authorized_problem(session, problem_id, problem_token)
    return _state_response(get_problem_state(session, problem))


@router.post("/{problem_id}/answers", response_model=ProblemStateResponse)
def answer_problem(
    problem_id: uuid.UUID,
    request: AnswerProblemRequest,
    session: SessionDependency,
    problem_token: ProblemToken = "",
) -> ProblemStateResponse:
    problem = _authorized_problem(session, problem_id, problem_token)
    try:
        state_value = record_answer(
            session,
            problem,
            request.field,
            request.value,
            request.knowledge_status,
        )
    except ProblemStateConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    return _state_response(state_value)


@router.post(
    "/{problem_id}/confirm",
    response_model=ConfirmedProblemResponse,
    status_code=status.HTTP_201_CREATED,
)
def confirm_problem(
    problem_id: uuid.UUID,
    session: SessionDependency,
    problem_token: ProblemToken = "",
) -> ProblemStateResponse:
    problem = _authorized_problem(session, problem_id, problem_token)
    try:
        confirm_public_problem(session, problem)
    except IncompleteProblemError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "problem_incomplete",
                "missing_fields": [field.value for field in error.missing_fields],
            },
        ) from error
    except ProblemStateConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code},
        ) from error
    return _state_response(get_problem_state(session, problem))


@router.post("/{problem_id}/revisions", response_model=ProblemStateResponse)
def reopen_problem_for_revision(
    problem_id: uuid.UUID,
    session: SessionDependency,
    problem_token: ProblemToken = "",
) -> ProblemStateResponse:
    problem = _authorized_problem(session, problem_id, problem_token)
    return _state_response(reopen_problem(session, problem))
