from sqlalchemy.orm import Session

from pci.answers.evidence import collect_evidence
from pci.answers.provider import AnswerProvider, AnswerProviderError
from pci.answers.schemas import Analysis, AnswerRequest, EvidenceSource, ResearchAnswer
from pci.productions.search import search_productions


def verify_citations(analysis: Analysis, sources: list[EvidenceSource]) -> None:
    excerpts = {e.id: " ".join(e.text.split()) for s in sources for e in s.excerpts}
    for statement in analysis.statements():
        for citation in statement.citations:
            quote = " ".join(citation.quote.split())
            if len(quote) < 20 or quote not in excerpts.get(citation.excerpt_id, ""):
                raise AnswerProviderError("answer_citation_invalid")


def answer_problem(
    session: Session, request: AnswerRequest, provider: AnswerProvider | None
) -> ResearchAnswer:
    results = search_productions(
        session,
        request.q,
        institution=request.institution,
        production_type=request.type,
        publication_year=request.publication_year,
        page_size=12,
    )
    response = ResearchAnswer(
        query=request.q,
        status="insufficient_evidence",
        total_matches=results.total,
        message="Não há texto suficiente nos trabalhos recuperados para responder. "
        "Isso não demonstra que o problema seja impossível de resolver.",
    )
    if not results.items:
        return response
    if provider is None:
        response.status = "unavailable"
        response.message = (
            "A síntese científica ainda não está ativada. "
            "Você pode consultar os trabalhos encontrados abaixo."
        )
        return response
    response.sources = collect_evidence(session, results.items, request.q)
    if not response.sources:
        return response
    try:
        analysis = provider.synthesize(request.q, response.sources)
        verify_citations(analysis, response.sources)
    except (AnswerProviderError, ValueError):
        response.status = "unavailable"
        response.message = (
            "Não foi possível produzir uma síntese com referências conferidas "
            "agora. Os trabalhos encontrados continuam disponíveis abaixo."
        )
        response.sources = []
        return response
    response.analysis = analysis
    if analysis.outcome == "insufficient":
        response.message = (
            "Os trechos analisados não oferecem evidência suficiente para "
            "concluir como enfrentar este problema. Isso não significa impossibilidade."
        )
    else:
        response.status = "ready"
        response.message = (
            "Síntese automática preliminar, sem revisão humana. "
            "As referências permitem conferir os trechos; a aplicação exige avaliação local."
        )
    return response
