import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.models.publication import PublishedContribution
from pci.problems.models import ProblemContextVersion, PublicProblem

_STOPWORDS = {
    "a",
    "as",
    "ao",
    "aos",
    "com",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "ou",
    "para",
    "por",
    "que",
    "sem",
    "uma",
    "um",
}


@dataclass(frozen=True)
class EvidenceMatch:
    scientific_contribution_id: uuid.UUID
    contribution_type: str | None
    description: str | None
    problem_or_phenomenon: str | None
    evidence_results: str | None
    barriers_limitations: str | None
    applicability: str | None
    institution: str | None
    publication_year: int | None
    source_scope: str | None
    match_score: float
    matched_terms: tuple[str, ...]
    explanation: str


@dataclass(frozen=True)
class EvidenceMap:
    problem_id: uuid.UUID
    problem_version: int
    status: Literal["ready", "no_validated_evidence"]
    query_summary: str
    items: tuple[EvidenceMatch, ...]


def _terms(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_value = "".join(character for character in normalized if not unicodedata.combining(character))
    return {
        token
        for token in re.findall(r"[a-z0-9]+", ascii_value)
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _scientific_text(values: dict[str, object]) -> str:
    public_fields = (
        "problem_or_phenomenon",
        "description",
        "mechanism",
        "population",
        "service",
        "territory",
        "methodology",
        "evidence_results",
        "barriers_limitations",
        "applicability",
        "required_resources",
        "maturity",
        "risks_contraindications",
    )
    return " ".join(str(values[field]) for field in public_fields if values.get(field))


def build_evidence_map(
    session: Session,
    problem: PublicProblem,
    *,
    limit: int = 10,
) -> EvidenceMap:
    context = session.scalar(
        select(ProblemContextVersion).where(
            ProblemContextVersion.problem_id == problem.id,
            ProblemContextVersion.version == problem.current_version_number,
        )
    )
    if context is None:
        raise ValueError("confirmed problem has no context version")

    query_terms = _terms(f"{problem.description} {context.structured_summary}")
    matches: list[EvidenceMatch] = []
    projections = session.scalars(
        select(PublishedContribution).where(PublishedContribution.active.is_(True))
    ).all()
    for projection in projections:
        contribution_terms = _terms(_scientific_text(projection.scientific_values))
        overlap = sorted(query_terms & contribution_terms)
        if not overlap:
            continue
        score = round(len(overlap) / max(len(query_terms), 1), 4)
        values = projection.scientific_values
        matches.append(
            EvidenceMatch(
                scientific_contribution_id=projection.scientific_contribution_id,
                contribution_type=projection.contribution_type,
                description=_optional_text(values.get("description")),
                problem_or_phenomenon=_optional_text(values.get("problem_or_phenomenon")),
                evidence_results=_optional_text(values.get("evidence_results")),
                barriers_limitations=_optional_text(values.get("barriers_limitations")),
                applicability=_optional_text(values.get("applicability")),
                institution=projection.institution,
                publication_year=projection.publication_year,
                source_scope=projection.source_scope,
                match_score=score,
                matched_terms=tuple(overlap),
                explanation=(
                    "Correspondência inicial com termos do problema confirmado: "
                    + ", ".join(overlap)
                    + "."
                ),
            )
        )

    matches.sort(
        key=lambda item: (
            -item.match_score,
            -(item.publication_year or 0),
            str(item.scientific_contribution_id),
        )
    )
    selected = tuple(matches[:limit])
    return EvidenceMap(
        problem_id=problem.id,
        problem_version=context.version,
        status="ready" if selected else "no_validated_evidence",
        query_summary=context.structured_summary,
        items=selected,
    )


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None
