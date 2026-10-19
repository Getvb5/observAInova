import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pci.problems.models import (
    KnowledgeStatus,
    ProblemField,
    ProblemStatus,
)


class ProblemSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class CreateProblemRequest(ProblemSchema):
    description: str = Field(min_length=1, max_length=5000)

    @field_validator("description")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("description must not be blank")
        return value


class AnswerProblemRequest(ProblemSchema):
    field: ProblemField
    value: str | None = Field(default=None, max_length=5000)
    knowledge_status: KnowledgeStatus


class NextQuestionResponse(ProblemSchema):
    field: ProblemField
    prompt: str
    accepts_unknown: bool


class ProblemFieldResponse(ProblemSchema):
    value: str | None
    knowledge_status: KnowledgeStatus


class ProblemStateResponse(ProblemSchema):
    problem_id: uuid.UUID
    status: ProblemStatus
    description: str
    fields: dict[ProblemField, ProblemFieldResponse | None]
    next_question: NextQuestionResponse | None
    missing_fields: list[ProblemField]
    ready_to_confirm: bool
    current_version: int
    structured_summary: str | None
    map_status: Literal["not_ready", "awaiting_validated_contributions"]


class CreatedProblemResponse(ProblemSchema):
    problem_id: uuid.UUID
    edit_token: str
    state: ProblemStateResponse


class ConfirmedProblemResponse(ProblemStateResponse):
    map_status: Literal["awaiting_validated_contributions"]


class ProblemEvidenceMapItem(ProblemSchema):
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
    matched_terms: list[str]
    explanation: str


class ProblemEvidenceMapResponse(ProblemSchema):
    problem_id: uuid.UUID
    problem_version: int
    status: Literal["ready", "no_validated_evidence"]
    query_summary: str
    items: list[ProblemEvidenceMapItem]
