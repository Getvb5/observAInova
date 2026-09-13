import uuid
from typing import Any

from sqlalchemy.orm import Session

from pci.productions import repository
from pci.productions.schemas import (
    PublicProductionDetail,
    PublicProductionPage,
    PublicProductionSummary,
    PublicQuality,
    PublicSource,
)


def list_public_productions(
    session: Session,
    filters: repository.ProductionFilters,
    *,
    page: int,
    page_size: int,
) -> PublicProductionPage:
    records, total = repository.list_public_productions(
        session,
        filters,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return PublicProductionPage(
        items=[_summary(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_public_production(
    session: Session, production_id: uuid.UUID
) -> PublicProductionDetail | None:
    record = repository.get_public_production(session, production_id)
    if record is None:
        return None
    version = record.version
    summary = _summary(record)
    return PublicProductionDetail(
        **summary.model_dump(),
        abstract=version.abstract,
        language=version.language,
        identifiers=_string_dict(version.identifiers),
        keywords=[item for item in (version.keywords or []) if isinstance(item, str)],
        publishers=[item for item in (version.publishers or []) if isinstance(item, str)],
        rights=version.rights,
        full_text_available=_live_full_text_available(record),
    )


def _summary(record: repository.PublicProductionRecord) -> PublicProductionSummary:
    version = record.version
    access_available = version.source_url is not None and not record.source_tombstoned
    return PublicProductionSummary(
        id=record.production.id,
        title=version.title,
        publication_date=version.publication_date,
        publication_year=version.publication_year,
        type=version.type,
        authors=list(record.authors),
        institutions=list(record.institutions),
        territory_relations=list(record.territory_relations),
        source=PublicSource(
            code=record.source.code if record.source is not None else None,
            name=record.source.name if record.source is not None else None,
            source_identifier=(
                record.raw_record.source_identifier
                if record.raw_record is not None
                else None
            ),
            source_url=version.source_url,
            access_status="available" if access_available else "unavailable",
        ),
        quality=PublicQuality(missing_fields=_missing_fields(version.normalization_report)),
    )


def _live_full_text_available(record: repository.PublicProductionRecord) -> bool:
    raw = record.raw_record
    return bool(
        raw is not None
        and not raw.is_tombstone
        and not record.source_tombstoned
        and raw.stored_object is not None
        and raw.stored_object.status == "stored"
    )


def _missing_fields(report: dict[str, Any] | None) -> list[str]:
    if report is None:
        return []
    value = report.get("missing_fields")
    if not isinstance(value, list):
        return []
    return [field for field in value if isinstance(field, str)]


def _string_dict(value: dict[str, Any] | None) -> dict[str, str]:
    if value is None:
        return {}
    return {key: item for key, item in value.items() if isinstance(item, str)}
