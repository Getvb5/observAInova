import uuid
from typing import Literal

from pydantic import Field, model_validator

from pci.models.enums import ProductionType
from pci.productions.schemas import PublicSchema


class AnswerRequest(PublicSchema):
    q: str = Field(min_length=2, max_length=300)
    institution: str | None = Field(default=None, max_length=255)
    type: ProductionType | None = None
    publication_year: int | None = Field(default=None, ge=1, le=9999)


class Excerpt(PublicSchema):
    id: str
    text: str
    page: int | None


class EvidenceSource(PublicSchema):
    id: str
    production_id: uuid.UUID
    production_version_id: uuid.UUID
    text_version_id: uuid.UUID | None
    title: str
    authors: list[str]
    year: int | None
    url: str | None
    reading_scope: Literal["abstract_only", "full_text_excerpts"]
    excerpts: list[Excerpt]


class Citation(PublicSchema):
    excerpt_id: str
    quote: str = Field(min_length=20, max_length=300)


class Statement(PublicSchema):
    text: str = Field(min_length=10, max_length=1000)
    basis: Literal["finding", "inference"]
    citations: list[Citation] = Field(min_length=1, max_length=3)


class Analysis(PublicSchema):
    outcome: Literal["supported_in_study", "conditional", "insufficient"]
    context: list[Statement] = Field(max_length=4)
    feasibility: list[Statement] = Field(max_length=4)
    pathways: list[Statement] = Field(max_length=4)
    potentials: list[Statement] = Field(max_length=4)
    limitations: list[Statement] = Field(max_length=4)

    @model_validator(mode="after")
    def require_support(self) -> "Analysis":
        if self.outcome != "insufficient" and not (
            self.context and self.feasibility and self.limitations
        ):
            raise ValueError("A supported answer requires context, feasibility and limits")
        return self

    def statements(self) -> list[Statement]:
        return self.context + self.feasibility + self.pathways + self.potentials + self.limitations


class ResearchAnswer(PublicSchema):
    query: str
    status: Literal["ready", "insufficient_evidence", "unavailable"]
    message: str
    total_matches: int
    sources: list[EvidenceSource] = Field(default_factory=list)
    analysis: Analysis | None = None
    validation_status: Literal["automated_unreviewed"] = "automated_unreviewed"
