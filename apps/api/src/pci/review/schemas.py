import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pci.claims.enums import ContributionField
from pci.models.contributions import FieldDecisionAction


class InternalSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldDecisionRequest(InternalSchema):
    field: ContributionField
    action: FieldDecisionAction
    value: str | None = Field(default=None, max_length=20_000)
    grounding_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    reason: str | None = Field(default=None, max_length=4_000)


class SplitCaseRequest(InternalSchema):
    partitions: list[list[uuid.UUID]] = Field(min_length=2, max_length=20)


class MergeCasesRequest(InternalSchema):
    review_case_ids: list[uuid.UUID] = Field(min_length=2, max_length=20)


class SamplingRunRequest(InternalSchema):
    candidate_ids: list[uuid.UUID] = Field(min_length=1, max_length=10_000)
    target_size: int = Field(ge=1, le=10_000)
    test_fraction: str
    double_code_fraction: str
    seed: str = Field(min_length=1, max_length=255)
    rule_version: str = Field(min_length=1, max_length=100)


class SourceProcessingPolicyRequest(InternalSchema):
    institution_sector: Literal["public"]
    institution_state: Literal["PE"]
    corpus_types: list[Literal["thesis", "dissertation"]]
    analysis_year_start: int
    analysis_year_end: int
    current_year: int
    document_host_allowlist: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_window(self) -> "SourceProcessingPolicyRequest":
        if self.analysis_year_start > self.analysis_year_end:
            raise ValueError("analysis window is invalid")
        if self.current_year <= self.analysis_year_end:
            raise ValueError("current year must follow the analysis window")
        if set(self.corpus_types) != {"thesis", "dissertation"}:
            raise ValueError("corpus types must contain thesis and dissertation")
        return self
