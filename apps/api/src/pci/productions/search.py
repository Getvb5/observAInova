"""Read-only expression search over public metadata and published intelligence."""

import json
import re
import unicodedata
import uuid
from typing import Any, Literal
from typing import cast as typing_cast

from pydantic import Field
from sqlalchemy import Text, case, cast, exists, func, literal, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from pci.bootstrap import config_from_environment
from pci.models.actors import Organization, ProductionOrganization
from pci.models.enums import ProductionType
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import Source
from pci.models.publication import PublishedContribution
from pci.productions.repository import (
    ProductionFilters,
    ProductionTuple,
    _hydrate_records,
    _public_statement,
)
from pci.productions.schemas import PublicProductionDetail, PublicSchema
from pci.productions.service import public_production_detail
from pci.publication.schemas import PublicContribution, PublicScientificValues

STOPWORDS = frozenset(
    [
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
        "como",
        "qual",
        "quais",
        "sobre",
    ]
)
ACCENTED = "áàâãäéèêëíìîïóòôõöúùûüçñ"
UNACCENTED = "aaaaaeeeeiiiiooooouuuucn"


class SearchResult(PublicProductionDetail):
    matched_terms: list[str]
    validated_contributions: list[PublicContribution] = Field(default_factory=list)


class SearchFacets(PublicSchema):
    institutions: list[str]
    years: list[int]


class SearchPage(PublicSchema):
    query: str
    items: list[SearchResult]
    total: int
    page: int
    page_size: int
    facets: SearchFacets


def normalize(value: object) -> str:
    text = str(value or "")
    # SQLite JSON may store escaped Unicode; PostgreSQL JSONB renders it literally.
    if text.startswith(("[", "{")):
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False)
        except (ValueError, TypeError):
            pass
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )


def query_terms(query: str) -> list[str]:
    return list(
        dict.fromkeys(
            term
            for term in re.findall(r"[a-z0-9]+", normalize(query))
            if len(term) >= 2 and term not in STOPWORDS
        )
    )


def _normalized(session: Session, column: Any) -> ColumnElement[str]:
    value = func.coalesce(cast(column, Text), "")
    if session.get_bind().dialect.name == "sqlite":
        connection = session.connection().connection.driver_connection
        assert connection is not None
        connection.create_function("pci_search_normalize", 1, normalize, deterministic=True)
        return func.pci_search_normalize(value)
    return func.translate(func.lower(value), ACCENTED, UNACCENTED)


def search_productions(
    session: Session,
    query: str,
    *,
    institution: str | None = None,
    production_type: ProductionType | None = None,
    publication_year: int | None = None,
    sort: Literal["relevance", "recent"] = "relevance",
    page: int = 1,
    page_size: int = 10,
) -> SearchPage:
    terms = query_terms(query)
    if not terms:
        raise ValueError("Digite pelo menos um termo com duas letras para buscar.")
    if len(terms) > 32:
        raise ValueError("Use uma expressão com até 32 termos.")

    corpus = config_from_environment()
    statement = _public_statement(ProductionFilters()).where(
        ProductionVersion.type.in_((ProductionType.THESIS, ProductionType.DISSERTATION)),
        ProductionVersion.publication_year.between(
            corpus.analysis_year_start, corpus.analysis_year_end
        ),
        Source.schedule["institution_sector"].as_string() == "public",
        Source.schedule["institution_state"].as_string() == "PE",
    )
    title = _normalized(session, ProductionVersion.title)
    abstract = _normalized(session, ProductionVersion.abstract)
    keywords = _normalized(session, ProductionVersion.keywords)
    scientific_values: ColumnElement[str] = literal("")
    for field in PublicScientificValues.model_fields:
        scientific_values = (
            scientific_values
            + literal(" ")
            + func.coalesce(PublishedContribution.scientific_values[field].as_string(), "")
        )
    scientific_text = _normalized(session, scientific_values)
    matches = []
    scores = []
    for term in terms:
        in_title = title.contains(term, autoescape=True)
        in_abstract = abstract.contains(term, autoescape=True)
        in_keywords = keywords.contains(term, autoescape=True)
        in_science = exists(
            select(1).where(
                PublishedContribution.production_id == Production.id,
                PublishedContribution.active.is_(True),
                scientific_text.contains(term, autoescape=True),
            )
        )
        any_match = or_(in_title, in_abstract, in_keywords, in_science)
        matches.append(any_match)
        # Term coverage takes priority; title/keywords break ties. No confidence claim.
        scores.append(
            case((any_match, 100), else_=0)
            + case((in_title, 6), else_=0)
            + case((in_keywords, 4), else_=0)
            + case((in_abstract, 2), else_=0)
            + case((in_science, 3), else_=0)
        )
    statement = statement.where(or_(*matches))

    matching_ids = statement.with_only_columns(Production.id).subquery()
    institutions = list(
        session.scalars(
            select(Organization.name)
            .join(ProductionOrganization, ProductionOrganization.organization_id == Organization.id)
            .join(matching_ids, matching_ids.c.id == ProductionOrganization.production_id)
            .distinct()
            .order_by(Organization.name)
        )
    )
    years = list(
        session.scalars(
            statement.with_only_columns(ProductionVersion.publication_year)
            .distinct()
            .order_by(ProductionVersion.publication_year.desc())
        )
    )

    if institution:
        statement = statement.where(
            exists(
                select(1)
                .select_from(ProductionOrganization)
                .join(Organization, Organization.id == ProductionOrganization.organization_id)
                .where(
                    ProductionOrganization.production_id == Production.id,
                    Organization.name == institution,
                )
            )
        )
    if production_type is not None:
        statement = statement.where(ProductionVersion.type == production_type)
    if publication_year is not None:
        statement = statement.where(ProductionVersion.publication_year == publication_year)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    relevance = sum(scores, literal(0))
    ordering = [ProductionVersion.publication_year.desc(), Production.id]
    if sort == "relevance":
        ordering.insert(0, relevance.desc())
    rows = typing_cast(
        list[ProductionTuple],
        list(
            session.execute(
                statement.order_by(*ordering).offset((page - 1) * page_size).limit(page_size)
            ).tuples()
        ),
    )
    records = _hydrate_records(session, rows)
    contributions: dict[uuid.UUID, list[PublicContribution]] = {
        record.production.id: [] for record in records
    }
    if contributions:
        projections = session.scalars(
            select(PublishedContribution)
            .where(
                PublishedContribution.production_id.in_(contributions),
                PublishedContribution.active.is_(True),
            )
            .order_by(PublishedContribution.published_at.desc(), PublishedContribution.id)
        )
        for projection in projections:
            contributions[projection.production_id].append(
                PublicContribution.model_validate(projection)
            )
    items = []
    for record in records:
        detail = public_production_detail(record)
        approved = contributions[record.production.id]
        text = normalize(
            " ".join(
                [
                    detail.title,
                    detail.abstract or "",
                    " ".join(detail.keywords),
                    *(
                        " ".join(
                            str(value)
                            for value in item.scientific_values.model_dump(
                                exclude_none=True
                            ).values()
                        )
                        for item in approved
                    ),
                ]
            )
        )
        items.append(
            SearchResult(
                **detail.model_dump(),
                matched_terms=[term for term in terms if term in text],
                validated_contributions=approved,
            )
        )
    return SearchPage(
        query=query.strip(),
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        facets=SearchFacets(
            institutions=institutions, years=[year for year in years if year is not None]
        ),
    )
