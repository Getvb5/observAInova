from fastapi import APIRouter, HTTPException, Request, Response

from pci.answers.provider import configured_provider
from pci.answers.schemas import AnswerRequest, ResearchAnswer
from pci.answers.service import answer_problem
from pci.api_dependencies import SessionDependency

router = APIRouter(prefix="/answers", tags=["research answers"])


@router.post("", response_model=ResearchAnswer)
def answer(
    body: AnswerRequest, session: SessionDependency, request: Request, response: Response
) -> ResearchAnswer:
    response.headers["Cache-Control"] = "no-store"
    try:
        provider = (
            request.app.state.answer_provider
            if hasattr(request.app.state, "answer_provider")
            else configured_provider()
        )
    except ValueError:
        provider = None
    try:
        return answer_problem(session, body, provider)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
