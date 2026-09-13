import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pci.models.enums import ProductionType, TerritoryRelation


class PublicSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicSource(PublicSchema):
    code: str | None
    name: str | None
    source_identifier: str | None
    source_url: str | None
    access_status: Literal["available", "unavailable"]


class PublicQuality(PublicSchema):
    missing_fields: list[str] = Field(default_factory=list)


class PublicProductionSummary(PublicSchema):
    id: uuid.UUID
    title: str
    publication_date: date | None
    publication_year: int | None
    type: ProductionType | None
    authors: list[str]
    institutions: list[str]
    territory_relations: list[TerritoryRelation]
    source: PublicSource
    quality: PublicQuality


class PublicProductionDetail(PublicProductionSummary):
    abstract: str | None
    language: str | None
    identifiers: dict[str, str]
    keywords: list[str]
    publishers: list[str]
    rights: str | None
    full_text_available: bool


class PublicProductionPage(PublicSchema):
    items: list[PublicProductionSummary]
    total: int
    page: int
    page_size: int
