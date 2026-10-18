import uuid
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pci.claims.enums import ContributionField, ContributionType
from pci.models.documents import DocumentTextScope


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentPagePayload(StrictContract):
    page_number: int = Field(ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)


class ExtractionDocument(StrictContract):
    document_text_version_id: uuid.UUID
    checksum: str = Field(min_length=64, max_length=64)
    scope: DocumentTextScope
    normalized_text: str
    pages: list[DocumentPagePayload] = Field(default_factory=list)


class GroundingPayload(StrictContract):
    document_text_version_id: uuid.UUID
    page_number: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=255)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    quote: str = Field(min_length=1)


class CandidateClaimPayload(StrictContract):
    field: ContributionField
    value: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    notes: str | None = Field(default=None, max_length=4000)
    groundings: list[GroundingPayload] = Field(min_length=1)

    @field_validator("value")
    @classmethod
    def value_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("claim value cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_contribution_type(self) -> "CandidateClaimPayload":
        if self.field is ContributionField.CONTRIBUTION_TYPE:
            ContributionType(self.value)
        return self


class CandidateContributionPayload(StrictContract):
    claims: list[CandidateClaimPayload] = Field(min_length=1)


class ProviderExtraction(StrictContract):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=255)
    schema_version: str = Field(min_length=1, max_length=100)
    instruction_version: str = Field(min_length=1, max_length=100)
    contributions: list[CandidateContributionPayload] = Field(default_factory=list)
    raw_response: dict[str, Any] | None = None


class ExtractionProvider(Protocol):
    provider_name: str
    model_name: str
    schema_version: str
    instruction_version: str

    def extract(self, document: ExtractionDocument) -> ProviderExtraction: ...
