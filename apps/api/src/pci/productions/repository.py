import uuid
from dataclasses import dataclass
from typing import cast

from sqlalchemy import Select, String, and_, exists, func, or_, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.orm import Session

from pci.models.actors import Authorship, Organization, Person, ProductionOrganization
from pci.models.enums import ProductionType, RecordVisibility, TerritoryRelation
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import RawRecord, Source
from pci.models.territory import ProductionTerritory


@dataclass(frozen=True, slots=True)
class ProductionFilters:
    institution: str | None = None
    production_type: ProductionType | None = None
    publication_year: int | None = None
    territory_relation: TerritoryRelation | None = None


@dataclass(frozen=True, slots=True)
class PublicProductionRecord:
    production: Production
    version: ProductionVersion
    raw_record: RawRecord | None
    source: Source | None
    authors: tuple[str, ...]
    institutions: tuple[str, ...]
    territory_relations: tuple[TerritoryRelation, ...]
    source_tombstoned: bool


ProductionTuple = tuple[Production, ProductionVersion, RawRecord | None, Source | None]
RecordSelect = Select[tuple[Production, ProductionVersion, RawRecord, Source]]


def list_public_productions(
    session: Session,
    filters: ProductionFilters,
    *,
    offset: int,
    limit: int,
) -> tuple[list[PublicProductionRecord], int]:
    statement = _public_statement(filters)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = cast(
        list[ProductionTuple],
        list(
            session.execute(
                statement.order_by(
                    ProductionVersion.publication_year.desc(),
                    ProductionVersion.title,
                    Production.id,
                )
                .offset(offset)
                .limit(limit)
            ).tuples()
        ),
    )
    return _hydrate_records(session, rows), total


def get_public_production(
    session: Session, production_id: uuid.UUID
) -> PublicProductionRecord | None:
    row = cast(
        ProductionTuple | None,
        session.execute(
            _public_statement(ProductionFilters()).where(Production.id == production_id)
        )
        .tuples()
        .one_or_none(),
    )
    return _hydrate_records(session, [row])[0] if row is not None else None


def _public_statement(filters: ProductionFilters) -> RecordSelect:
    statement = (
        select(Production, ProductionVersion, RawRecord, Source)
        .join(
            ProductionVersion,
            and_(
                ProductionVersion.production_id == Production.id,
                ProductionVersion.version == Production.current_version_number,
            ),
        )
        .outerjoin(RawRecord, RawRecord.id == ProductionVersion.raw_record_id)
        .outerjoin(Source, Source.id == RawRecord.source_id)
        .where(Production.visibility == RecordVisibility.METADATA_PUBLIC)
    )
    if filters.production_type is not None:
        statement = statement.where(ProductionVersion.type == filters.production_type)
    if filters.publication_year is not None:
        statement = statement.where(ProductionVersion.publication_year == filters.publication_year)
    if filters.institution is not None:
        statement = statement.where(
            exists(
                select(1)
                .select_from(ProductionOrganization)
                .join(
                    Organization,
                    Organization.id == ProductionOrganization.organization_id,
                )
                .where(
                    ProductionOrganization.production_id == Production.id,
                    Organization.name == filters.institution,
                )
            )
        )
    if filters.territory_relation is not None:
        statement = statement.where(
            exists(
                select(1)
                .select_from(ProductionTerritory)
                .where(
                    ProductionTerritory.production_id == Production.id,
                    ProductionTerritory.relation == filters.territory_relation,
                )
            )
        )
    return statement


def _hydrate_records(
    session: Session,
    rows: list[ProductionTuple],
) -> list[PublicProductionRecord]:
    production_ids = [production.id for production, _, _, _ in rows]
    source_tombstone_states = _source_tombstone_states(session, rows)
    authors: dict[uuid.UUID, list[tuple[int, str]]] = {
        production_id: [] for production_id in production_ids
    }
    institutions: dict[uuid.UUID, list[str]] = {
        production_id: [] for production_id in production_ids
    }
    territories: dict[uuid.UUID, set[TerritoryRelation]] = {
        production_id: set() for production_id in production_ids
    }
    if production_ids:
        for production_id, position, name in session.execute(
            select(Authorship.production_id, Authorship.position, Person.name)
            .join(Person, Person.id == Authorship.person_id)
            .where(Authorship.production_id.in_(production_ids))
        ):
            authors[production_id].append((position, name))
        for production_id, name in session.execute(
            select(ProductionOrganization.production_id, Organization.name)
            .join(
                Organization,
                Organization.id == ProductionOrganization.organization_id,
            )
            .where(ProductionOrganization.production_id.in_(production_ids))
        ):
            institutions[production_id].append(name)
        for production_id, relation in session.execute(
            select(ProductionTerritory.production_id, ProductionTerritory.relation).where(
                ProductionTerritory.production_id.in_(production_ids)
            )
        ):
            territories[production_id].add(relation)
    return [
        PublicProductionRecord(
            production=production,
            version=version,
            raw_record=raw_record,
            source=source,
            authors=tuple(name for _, name in sorted(authors[production.id])),
            institutions=tuple(sorted(set(institutions[production.id]))),
            territory_relations=tuple(
                sorted(territories[production.id], key=lambda relation: relation.value)
            ),
            source_tombstoned=source_tombstone_states[production.id],
        )
        for production, version, raw_record, source in rows
    ]


def _source_tombstone_states(
    session: Session, rows: list[ProductionTuple]
) -> dict[uuid.UUID, bool]:
    result = {production.id: False for production, _, _, _ in rows}
    source_identities = {
        (raw_record.source_id, raw_record.source_identifier)
        for _, _, raw_record, _ in rows
        if raw_record is not None
    }
    if not source_identities:
        return result

    identity_filters = [
        and_(
            RawRecord.source_id == source_id,
            RawRecord.source_identifier == source_identifier,
        )
        for source_id, source_identifier in source_identities
    ]
    ranked_tombstones = (
        select(
            RawRecord.id.label("raw_record_id"),
            func.row_number()
            .over(
                partition_by=(RawRecord.source_id, RawRecord.source_identifier),
                order_by=(
                    RawRecord.state_sequence.desc(),
                    sql_cast(RawRecord.id, String).desc(),
                ),
            )
            .label("identity_rank"),
        )
        .where(
            RawRecord.is_tombstone.is_(True),
            or_(*identity_filters),
        )
        .subquery()
    )
    newest_tombstones = {
        (tombstone.source_id, tombstone.source_identifier): tombstone
        for tombstone in session.scalars(
            select(RawRecord)
            .join(
                ranked_tombstones,
                RawRecord.id == ranked_tombstones.c.raw_record_id,
            )
            .where(ranked_tombstones.c.identity_rank == 1)
        )
    }

    for production, _, raw_record, _ in rows:
        if raw_record is None:
            continue
        newest_tombstone = newest_tombstones.get(
            (raw_record.source_id, raw_record.source_identifier)
        )
        result[production.id] = newest_tombstone is not None and (
            newest_tombstone.state_sequence > raw_record.state_sequence
        )
    return result
