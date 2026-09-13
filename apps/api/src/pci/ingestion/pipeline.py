"""Executable harvest → normalize → qualify orchestration path."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.ingestion.connectors.base import SourceConnector
from pci.ingestion.contracts import HarvestResult
from pci.ingestion.harvest import harvest_source
from pci.models.provenance import AuditEvent, HarvestObservation, RawRecord
from pci.normalization.service import persist_normalized_record
from pci.qualification.service import qualify_production, record_tombstone
from pci.storage.objects import ObjectStore

PIPELINE_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class IngestionPipelineResult:
    harvest: HarvestResult
    normalized_production_ids: tuple[uuid.UUID, ...]
    published_production_ids: tuple[uuid.UUID, ...]
    tombstoned_production_ids: tuple[uuid.UUID, ...]
    processing_failed: int = 0


async def harvest_normalize_qualify_source(
    session: Session,
    connector: SourceConnector,
    source_id: uuid.UUID,
    *,
    actor: str = "ingestion",
    object_store: ObjectStore | None = None,
) -> IngestionPipelineResult:
    """Run the sole safe publication path for source metadata.

    Raw observations are always preserved first.  Every non-tombstone observation
    is normalized, then explicitly structurally qualified before metadata enters
    the public projection.  Semantic intelligence is intentionally absent.
    """
    harvest = await harvest_source(
        session,
        connector,
        source_id,
        actor=actor,
        object_store=object_store,
    )
    _commit_pipeline_state(session)
    normalized: list[uuid.UUID] = []
    published: list[uuid.UUID] = []
    tombstoned: list[uuid.UUID] = []
    processing_failed = 0
    for raw_records in _harvested_raw_record_batches(session, harvest.run_id):
        for raw in raw_records:
            normalized_id: uuid.UUID | None = None
            published_id: uuid.UUID | None = None
            tombstoned_ids: tuple[uuid.UUID, ...] = ()
            raw_record_id = raw.id
            try:
                with session.begin_nested():
                    if raw.is_tombstone:
                        tombstoned_ids = record_tombstone(session, raw, actor=actor)
                    else:
                        normalized_id = persist_normalized_record(session, raw.id)
                        qualification = qualify_production(session, normalized_id, actor=actor)
                        if qualification.published:
                            published_id = normalized_id
                    session.flush()
            except ValueError as error:
                session.add(
                    AuditEvent(
                        actor=actor,
                        action="normalization.rejected",
                        entity_type="RawRecord",
                        entity_id=raw_record_id,
                        before=None,
                        after={"raw_record_id": str(raw_record_id)},
                        reason=str(error),
                    )
                )
                processing_failed += 1
                _commit_pipeline_state(session)
                continue
            except Exception as error:  # noqa: BLE001 - isolate every durable record
                session.add(
                    AuditEvent(
                        actor=actor,
                        action="ingestion.record_failed",
                        entity_type="RawRecord",
                        entity_id=raw_record_id,
                        before=None,
                        after={"raw_record_id": str(raw_record_id)},
                        reason=str(error),
                    )
                )
                processing_failed += 1
                _commit_pipeline_state(session)
                continue
            if normalized_id is not None:
                normalized.append(normalized_id)
            if published_id is not None:
                published.append(published_id)
            tombstoned.extend(tombstoned_ids)
            _commit_pipeline_state(session)
    return IngestionPipelineResult(
        harvest=harvest,
        normalized_production_ids=tuple(dict.fromkeys(normalized)),
        published_production_ids=tuple(dict.fromkeys(published)),
        tombstoned_production_ids=tuple(dict.fromkeys(tombstoned)),
        processing_failed=processing_failed,
    )


def _harvested_raw_record_batches(
    session: Session, harvest_run_id: uuid.UUID
) -> Iterator[list[RawRecord]]:
    after_position = 0
    while True:
        rows = session.execute(
            select(RawRecord, HarvestObservation.position)
            .join(
                HarvestObservation,
                HarvestObservation.raw_record_id == RawRecord.id,
            )
            .where(
                HarvestObservation.harvest_run_id == harvest_run_id,
                HarvestObservation.position > after_position,
            )
            .order_by(HarvestObservation.position)
            .limit(PIPELINE_BATCH_SIZE)
        ).all()
        if not rows:
            return
        yield [raw for raw, _ in rows]
        if len(rows) < PIPELINE_BATCH_SIZE:
            return
        after_position = rows[-1][1]


def _commit_pipeline_state(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
