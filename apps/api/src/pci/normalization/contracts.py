import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pci.models.enums import ProductionType


@dataclass(frozen=True, slots=True)
class NormalizedAuthor:
    name: str
    orcid: str | None = None
    organization: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedRecord:
    source_identifier: str
    title: str | None
    abstract: str | None
    publication_date: date | None
    publication_year: int | None
    language: str | None
    type: ProductionType | None
    identifiers: dict[str, str]
    authors: tuple[NormalizedAuthor, ...]
    organizations: tuple[str, ...]
    keywords: tuple[str, ...]
    publishers: tuple[str, ...]
    source_url: str | None
    rights: str | None
    full_text_available: bool
    missing_fields: tuple[str, ...]
    normalization_report: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MatchDecision:
    kind: Literal["new", "exact", "review"]
    production_id: uuid.UUID | None
    reasons: tuple[str, ...]
    score: float | None = None
