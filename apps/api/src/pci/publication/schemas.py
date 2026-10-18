import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from pci.models.publication import PublicationAction


class PublicationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: PublicationAction
    reason: str | None = Field(default=None, max_length=4_000)


class PublicScientificValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_or_phenomenon: str | None = None
    contribution_type: str | None = None
    description: str | None = None
    mechanism: str | None = None
    population: str | None = None
    service: str | None = None
    territory: str | None = None
    methodology: str | None = None
    evidence_results: str | None = None
    barriers_limitations: str | None = None
    applicability: str | None = None
    required_resources: str | None = None
    maturity: str | None = None
    risks_contraindications: str | None = None


class PublicGrounding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    source_scope: str
    page_number: int | None
    section: str | None
    quote: str


class PublicContribution(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: uuid.UUID
    scientific_contribution_id: uuid.UUID
    contribution_version_id: uuid.UUID
    production_id: uuid.UUID
    version: int
    contribution_type: str | None
    scientific_values: PublicScientificValues
    approved_groundings: list[PublicGrounding]
    institution: str | None
    publication_year: int | None
    source_scope: str | None
    production_type: str | None
    source_warning: str | None
    validated_at: datetime | None
    published_at: datetime
    original_url: str | None = None


class PublicContributionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublicContribution]
    page: int
    page_size: int
    total: int
