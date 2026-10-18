import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pci.models.documents import DocumentTextVersion
from pci.models.production import ProductionVersion
from pci.models.provenance import RawRecord, Source


def get_document_context(
    session: Session, production_version_id: uuid.UUID
) -> tuple[ProductionVersion, RawRecord, Source]:
    version = session.get(ProductionVersion, production_version_id)
    if version is None:
        raise ValueError(f"production version does not exist: {production_version_id}")
    raw = session.get(RawRecord, version.raw_record_id) if version.raw_record_id else None
    if raw is None:
        raise ValueError("production version has no source record")
    source = session.get(Source, raw.source_id)
    if source is None:
        raise ValueError("source record has no source")
    return version, raw, source


def next_text_version(session: Session, production_version_id: uuid.UUID) -> int:
    latest = session.scalar(
        select(func.max(DocumentTextVersion.version)).where(
            DocumentTextVersion.production_version_id == production_version_id
        )
    )
    return (latest or 0) + 1
