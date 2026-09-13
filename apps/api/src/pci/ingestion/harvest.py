import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pci.ingestion.connectors.base import SourceConnector
from pci.ingestion.contracts import HarvestedRecord, HarvestResult
from pci.models.base import utc_now
from pci.models.enums import HarvestStatus, RightsPolicy
from pci.models.provenance import (
    AuditEvent,
    HarvestObservation,
    HarvestRun,
    RawRecord,
    RawRecordObject,
    Source,
)
from pci.storage.objects import (
    ObjectStore,
    StoredObject,
    describe_full_text_if_permitted,
    store_full_text_if_permitted,
)

RAW_RECORD_STATE_CONSTRAINT = "uq_raw_records_source_identifier_state_sequence"
RAW_RECORD_STATE_ALLOCATION_ATTEMPTS = 4
STORAGE_ASSOCIATION_CONSTRAINTS = {
    "uq_raw_record_objects_raw_record",
    "uq_raw_record_objects_object_key",
}
STORAGE_CLAIM_ATTEMPTS = 4
STORAGE_ATTEMPT_LEASE = timedelta(minutes=15)
HARVEST_OBSERVATION_CONSTRAINT = "uq_harvest_observations_run_raw_record"


class ObjectDescriptorMismatch(ValueError):
    pass


async def harvest_source(
    session: Session,
    connector: SourceConnector,
    source_id: uuid.UUID,
    *,
    actor: str = "ingestion",
    object_store: ObjectStore | None = None,
) -> HarvestResult:
    source = session.get(Source, source_id)
    if source is None:
        raise ValueError(f"source does not exist: {source_id}")

    run = HarvestRun(source_id=source_id, status=HarvestStatus.RUNNING)
    session.add(run)
    session.flush()
    session.add(
        _audit_event(
            actor=actor,
            action="harvest_run.started",
            entity_type="HarvestRun",
            entity_id=run.id,
            before=None,
            after={"status": HarvestStatus.RUNNING.value},
        )
    )
    session.flush()

    errors: list[str] = []
    observed = 0
    flow_error: Exception | None = None
    try:
        async for record in connector.harvest(cursor=None):
            run.received += 1
            try:
                raw_record, inserted = _persist_raw_record(session, run, record, actor)
                if _record_harvest_observation(
                    session,
                    run,
                    raw_record,
                    position=run.received,
                    actor=actor,
                ):
                    observed += 1
                if inserted:
                    run.inserted += 1
                else:
                    run.unchanged += 1
                _store_full_text_for_raw_record(
                    session,
                    raw_record,
                    record,
                    source.rights_policy,
                    actor,
                    object_store,
                )
            except Exception as exc:  # noqa: BLE001 - isolate every record failure
                run.failed += 1
                errors.append(f"{record.source_identifier}: {exc}")
    except Exception as exc:  # noqa: BLE001 - always close and audit the run
        flow_error = exc
        run.failed += 1

    before = {"status": HarvestStatus.RUNNING.value}
    if flow_error is not None:
        run.status = HarvestStatus.FAILED
        run.error_summary = str(flow_error)
    elif run.failed:
        run.status = HarvestStatus.PARTIAL
        run.error_summary = "; ".join(errors)
    else:
        run.status = HarvestStatus.COMPLETED
    run.ended_at = utc_now()
    session.add(
        _audit_event(
            actor=actor,
            action="harvest_run.status_changed",
            entity_type="HarvestRun",
            entity_id=run.id,
            before=before,
            after=_run_snapshot(run),
            reason=run.error_summary,
        )
    )
    session.flush()
    return HarvestResult(
        run_id=run.id,
        status=run.status,
        received=run.received,
        inserted=run.inserted,
        unchanged=run.unchanged,
        failed=run.failed,
        observed=observed,
    )


def canonical_payload_checksum(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def canonical_harvested_record_checksum(record: HarvestedRecord) -> str:
    """Hash every immutable observation field, not only the source payload.

    Every field is explicit in the canonical envelope, including absent values, so
    source URL, rights, and full-text descriptor changes can never overwrite a
    prior observation.
    """
    descriptor = {
        "media_type": record.media_type,
        "byte_length": len(record.full_text) if record.full_text is not None else None,
        "checksum": (
            hashlib.sha256(record.full_text).hexdigest() if record.full_text is not None else None
        ),
    }
    return canonical_payload_checksum(
        {
            "payload": record.payload,
            "source_url": record.source_url,
            "rights": record.rights,
            "full_text": descriptor,
            "is_tombstone": record.is_tombstone,
        }
    )


def _persist_raw_record(
    session: Session,
    run: HarvestRun,
    record: HarvestedRecord,
    actor: str,
) -> tuple[RawRecord, bool]:
    checksum = canonical_harvested_record_checksum(record)
    for _ in range(RAW_RECORD_STATE_ALLOCATION_ATTEMPTS):
        latest = _latest_raw_record(session, run.source_id, record.source_identifier, lock=True)
        if latest is not None and latest.checksum == checksum:
            return latest, False
        state_sequence = (latest.state_sequence if latest is not None else 0) + 1

        try:
            with session.begin_nested():
                raw_record = _insert_raw_record(
                    session,
                    run,
                    record,
                    checksum,
                    state_sequence,
                    actor,
                )
        except IntegrityError as exc:
            if not _is_raw_record_state_conflict(exc):
                raise
            session.expire_all()
            winner = _raw_record_for_state_sequence(
                session,
                run.source_id,
                record.source_identifier,
                state_sequence,
            )
            if winner is not None and winner.checksum == checksum:
                return winner, False
            continue
        return raw_record, True
    raise RuntimeError("raw record state allocation retry was exhausted")


def _latest_raw_record(
    session: Session,
    source_id: uuid.UUID,
    source_identifier: str,
    *,
    lock: bool = False,
) -> RawRecord | None:
    statement = (
        select(RawRecord)
        .where(
            RawRecord.source_id == source_id,
            RawRecord.source_identifier == source_identifier,
        )
        .order_by(RawRecord.state_sequence.desc())
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    return session.scalar(statement)


def _raw_record_for_state_sequence(
    session: Session,
    source_id: uuid.UUID,
    source_identifier: str,
    state_sequence: int,
) -> RawRecord | None:
    return session.scalar(
        select(RawRecord).where(
            RawRecord.source_id == source_id,
            RawRecord.source_identifier == source_identifier,
            RawRecord.state_sequence == state_sequence,
        )
    )


def _insert_raw_record(
    session: Session,
    run: HarvestRun,
    record: HarvestedRecord,
    checksum: str,
    state_sequence: int,
    actor: str,
) -> RawRecord:

    raw_record = RawRecord(
        source_id=run.source_id,
        source_identifier=record.source_identifier,
        payload=record.payload,
        source_url=record.source_url,
        checksum=checksum,
        state_sequence=state_sequence,
        rights_snapshot=record.rights,
        is_tombstone=record.is_tombstone,
        harvest_run_id=run.id,
    )
    session.add(raw_record)
    session.flush()
    session.add(
        _audit_event(
            actor=actor,
            action="raw_record.created",
            entity_type="RawRecord",
            entity_id=raw_record.id,
            before=None,
            after={
                "source_id": str(run.source_id),
                "source_identifier": record.source_identifier,
                "checksum": checksum,
                "state_sequence": state_sequence,
                "rights_snapshot": record.rights,
                "source_url": record.source_url,
                "is_tombstone": record.is_tombstone,
            },
        )
    )
    if record.is_tombstone:
        session.add(
            _audit_event(
                actor=actor,
                action="raw_record.tombstone_created",
                entity_type="RawRecord",
                entity_id=raw_record.id,
                before=None,
                after={
                    "source_id": str(run.source_id),
                    "source_identifier": record.source_identifier,
                    "checksum": checksum,
                    "state_sequence": state_sequence,
                    "is_tombstone": True,
                },
            )
        )
    return raw_record


def _is_raw_record_state_conflict(exc: IntegrityError) -> bool:
    diagnostic = getattr(exc.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == RAW_RECORD_STATE_CONSTRAINT:
        return True
    sqlite_identity = (
        "UNIQUE constraint failed: raw_records.source_id, "
        "raw_records.source_identifier, raw_records.state_sequence"
    )
    return sqlite_identity in str(exc.orig)


def _record_harvest_observation(
    session: Session,
    run: HarvestRun,
    raw_record: RawRecord,
    *,
    position: int,
    actor: str,
) -> bool:
    try:
        with session.begin_nested():
            observation = HarvestObservation(
                harvest_run_id=run.id,
                raw_record_id=raw_record.id,
                position=position,
            )
            session.add(observation)
            session.flush()
            session.add(
                _audit_event(
                    actor=actor,
                    action="harvest_observation.created",
                    entity_type="HarvestObservation",
                    entity_id=observation.id,
                    before=None,
                    after={
                        "harvest_run_id": str(run.id),
                        "raw_record_id": str(raw_record.id),
                        "position": position,
                    },
                )
            )
    except IntegrityError as exc:
        if not _is_harvest_observation_conflict(exc):
            raise
        return False
    return True


def _is_harvest_observation_conflict(exc: IntegrityError) -> bool:
    diagnostic = getattr(exc.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == HARVEST_OBSERVATION_CONSTRAINT:
        return True
    message = str(exc.orig).casefold()
    return (
        "harvest_observations.harvest_run_id" in message
        and "harvest_observations.raw_record_id" in message
    )


def _store_full_text_for_raw_record(
    session: Session,
    raw_record: RawRecord,
    record: HarvestedRecord,
    policy: RightsPolicy,
    actor: str,
    object_store: ObjectStore | None,
) -> None:
    object_key = f"raw-records/{raw_record.id}/full-text"
    descriptor = describe_full_text_if_permitted(record, policy, object_key=object_key)
    if descriptor is None:
        return

    association, attempt_token = _create_storage_association(
        session,
        raw_record,
        descriptor,
        actor,
    )
    mismatches = _descriptor_mismatches(association, descriptor)
    if mismatches:
        reason = f"stored object descriptor mismatch: {', '.join(mismatches)}"
        snapshot = _storage_snapshot(association)
        session.add(
            _audit_event(
                actor=actor,
                action="raw_record_object.rejected",
                entity_type="RawRecordObject",
                entity_id=association.id,
                before=snapshot,
                after=snapshot,
                reason=reason,
            )
        )
        _commit_storage_state(session)
        raise ObjectDescriptorMismatch(reason)
    if attempt_token is None:
        attempt_token = _claim_storage_attempt(session, association.id, actor)
    if attempt_token is None:
        return

    try:
        store_full_text_if_permitted(
            record,
            policy,
            object_store=object_store,
            object_key=association.object_key,
        )
    except Exception as exc:
        _finalize_storage_attempt(
            session,
            association.id,
            attempt_token,
            actor=actor,
            status="failed",
            error_summary=str(exc),
        )
        raise

    _finalize_storage_attempt(
        session,
        association.id,
        attempt_token,
        actor=actor,
        status="stored",
        error_summary=None,
    )


def _create_storage_association(
    session: Session,
    raw_record: RawRecord,
    descriptor: StoredObject,
    actor: str,
) -> tuple[RawRecordObject, str | None]:
    association = _find_storage_association(session, raw_record.id)
    if association is not None:
        return association, None

    attempt_token = str(uuid.uuid4())
    attempt_started_at = utc_now()
    try:
        with session.begin_nested():
            association = RawRecordObject(
                raw_record_id=raw_record.id,
                object_key=descriptor.key,
                checksum=descriptor.checksum,
                media_type=descriptor.media_type,
                byte_length=descriptor.byte_length,
                rights_snapshot=descriptor.rights_snapshot,
                source_url=descriptor.source_url,
                status="pending",
                attempt_token=attempt_token,
                attempt_started_at=attempt_started_at,
            )
            session.add(association)
            session.flush()
            session.add(
                _storage_audit_event(
                    actor,
                    association,
                    action="raw_record_object.pending",
                    before=None,
                )
            )
    except IntegrityError as exc:
        if not _is_storage_association_conflict(exc):
            raise
        session.expire_all()
        winner = _find_storage_association(session, raw_record.id)
        if winner is None:
            raise
        return winner, None
    _commit_storage_state(session)
    return association, attempt_token


def _find_storage_association(session: Session, raw_record_id: uuid.UUID) -> RawRecordObject | None:
    return session.scalar(
        select(RawRecordObject).where(RawRecordObject.raw_record_id == raw_record_id)
    )


def _is_storage_association_conflict(exc: IntegrityError) -> bool:
    diagnostic = getattr(exc.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) in STORAGE_ASSOCIATION_CONSTRAINTS:
        return True
    message = str(exc.orig).casefold()
    return any(
        column in message
        for column in (
            "raw_record_objects.raw_record_id",
            "raw_record_objects.object_key",
        )
    )


def _claim_storage_attempt(
    session: Session,
    association_id: uuid.UUID,
    actor: str,
) -> str | None:
    for _ in range(STORAGE_CLAIM_ATTEMPTS):
        association = session.scalar(
            select(RawRecordObject)
            .where(RawRecordObject.id == association_id)
            .execution_options(populate_existing=True)
        )
        if association is None:
            raise RuntimeError("stored object association disappeared")
        if association.status == "stored":
            return None
        now = utc_now()
        lease_expires_at = now - STORAGE_ATTEMPT_LEASE
        if _has_active_storage_lease(association, lease_expires_at):
            return None
        before = _storage_snapshot(association)
        previous_status = association.status
        previous_token = association.attempt_token
        previous_started_at = association.attempt_started_at
        attempt_token = str(uuid.uuid4())
        token_predicate = (
            RawRecordObject.attempt_token.is_(None)
            if previous_token is None
            else RawRecordObject.attempt_token == previous_token
        )
        started_at_predicate = (
            RawRecordObject.attempt_started_at.is_(None)
            if previous_started_at is None
            else RawRecordObject.attempt_started_at == previous_started_at
        )
        reclaimable_predicate = or_(
            RawRecordObject.status == "failed",
            and_(
                RawRecordObject.status == "pending",
                or_(
                    RawRecordObject.attempt_token.is_(None),
                    RawRecordObject.attempt_started_at.is_(None),
                    RawRecordObject.attempt_started_at <= lease_expires_at,
                ),
            ),
        )
        claimed = cast(
            CursorResult[Any],
            session.execute(
                update(RawRecordObject)
                .where(
                    RawRecordObject.id == association_id,
                    RawRecordObject.status == previous_status,
                    RawRecordObject.status != "stored",
                    token_predicate,
                    started_at_predicate,
                    reclaimable_predicate,
                )
                .values(
                    status="pending",
                    attempt_token=attempt_token,
                    attempt_started_at=now,
                    error_summary=None,
                    stored_at=None,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        if claimed.rowcount != 1:
            session.expire_all()
            continue
        after = {
            **before,
            "status": "pending",
            "attempt_token": attempt_token,
            "attempt_started_at": now.isoformat(),
            "error_summary": None,
        }
        session.add(
            _storage_transition_audit_event(
                actor,
                association_id,
                action="raw_record_object.pending",
                before=before,
                after=after,
            )
        )
        _commit_storage_state(session)
        return attempt_token
    return None


def _finalize_storage_attempt(
    session: Session,
    association_id: uuid.UUID,
    attempt_token: str,
    *,
    actor: str,
    status: str,
    error_summary: str | None,
) -> bool:
    association = session.scalar(
        select(RawRecordObject)
        .where(
            RawRecordObject.id == association_id,
            RawRecordObject.status == "pending",
            RawRecordObject.attempt_token == attempt_token,
        )
        .execution_options(populate_existing=True)
    )
    if association is None:
        session.expire_all()
        return False
    before = _storage_snapshot(association)
    finalized = cast(
        CursorResult[Any],
        session.execute(
            update(RawRecordObject)
            .where(
                RawRecordObject.id == association_id,
                RawRecordObject.status == "pending",
                RawRecordObject.attempt_token == attempt_token,
            )
            .values(
                status=status,
                attempt_token=None,
                attempt_started_at=None,
                error_summary=error_summary,
                stored_at=utc_now() if status == "stored" else None,
            )
            .execution_options(synchronize_session=False)
        ),
    )
    if finalized.rowcount != 1:
        session.expire_all()
        return False
    after = {
        **before,
        "status": status,
        "attempt_token": None,
        "attempt_started_at": None,
        "error_summary": error_summary,
    }
    session.add(
        _storage_transition_audit_event(
            actor,
            association_id,
            action=f"raw_record_object.{status}",
            reason=error_summary,
            before=before,
            after=after,
        )
    )
    _commit_storage_state(session)
    return True


def _storage_transition_audit_event(
    actor: str,
    association_id: uuid.UUID,
    *,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    reason: str | None = None,
) -> AuditEvent:
    return _audit_event(
        actor=actor,
        action=action,
        entity_type="RawRecordObject",
        entity_id=association_id,
        before=before,
        after=after,
        reason=reason,
    )


def _storage_audit_event(
    actor: str,
    association: RawRecordObject,
    *,
    action: str,
    reason: str | None = None,
    before: dict[str, Any] | None,
) -> AuditEvent:
    return _audit_event(
        actor=actor,
        action=action,
        entity_type="RawRecordObject",
        entity_id=association.id,
        before=before,
        after=_storage_snapshot(association),
        reason=reason,
    )


def _descriptor_mismatches(association: RawRecordObject, descriptor: StoredObject) -> list[str]:
    fields = (
        ("object_key", "key"),
        ("checksum", "checksum"),
        ("media_type", "media_type"),
        ("byte_length", "byte_length"),
        ("rights_snapshot", "rights_snapshot"),
        ("source_url", "source_url"),
    )
    return [
        association_name
        for association_name, descriptor_name in fields
        if getattr(association, association_name) != getattr(descriptor, descriptor_name)
    ]


def _has_active_storage_lease(
    association: RawRecordObject,
    lease_expires_at: datetime,
) -> bool:
    if (
        association.status != "pending"
        or association.attempt_token is None
        or association.attempt_started_at is None
    ):
        return False
    started_at = association.attempt_started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return started_at > lease_expires_at


def _storage_snapshot(association: RawRecordObject) -> dict[str, Any]:
    attempt_started_at = association.attempt_started_at
    if attempt_started_at is not None and attempt_started_at.tzinfo is None:
        attempt_started_at = attempt_started_at.replace(tzinfo=UTC)
    return {
        "status": association.status,
        "attempt_token": association.attempt_token,
        "attempt_started_at": (
            attempt_started_at.isoformat() if attempt_started_at is not None else None
        ),
        "raw_record_id": str(association.raw_record_id),
        "object_key": association.object_key,
        "checksum": association.checksum,
        "media_type": association.media_type,
        "byte_length": association.byte_length,
        "rights_snapshot": association.rights_snapshot,
        "source_url": association.source_url,
        "error_summary": association.error_summary,
    }


def _commit_storage_state(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def _audit_event(
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    reason: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        reason=reason,
    )


def _run_snapshot(run: HarvestRun) -> dict[str, Any]:
    return {
        "status": run.status.value,
        "received": run.received,
        "inserted": run.inserted,
        "unchanged": run.unchanged,
        "failed": run.failed,
        "error_summary": run.error_summary,
    }
