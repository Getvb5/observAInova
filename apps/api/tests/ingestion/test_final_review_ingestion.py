import asyncio
import threading
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

import pci.ingestion.pipeline as ingestion_pipeline
from pci.ingestion.contracts import HarvestedRecord
from pci.ingestion.harvest import _claim_storage_attempt, harvest_source
from pci.ingestion.pipeline import harvest_normalize_qualify_source
from pci.models.base import Base, utc_now
from pci.models.enums import HarvestStatus, RecordVisibility, RightsPolicy
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import (
    AuditEvent,
    HarvestObservation,
    HarvestRun,
    RawRecord,
    RawRecordObject,
    Source,
)


class RecordsConnector:
    def __init__(self, records: list[HarvestedRecord]) -> None:
        self.records = records

    async def harvest(self, cursor: str | None) -> AsyncIterator[HarvestedRecord]:
        del cursor
        for record in self.records:
            yield record


class RecordingObjectStore:
    def __init__(self, *, error: str | None = None) -> None:
        self.error = error
        self.calls = 0
        self.objects: dict[str, bytes] = {}

    def put_object(
        self, key: str, content: bytes, media_type: str, metadata: dict[str, str]
    ) -> None:
        del media_type, metadata
        self.calls += 1
        if self.error is not None:
            raise OSError(self.error)
        self.objects[key] = content


class BlockingFailingObjectStore:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release

    def put_object(
        self, key: str, content: bytes, media_type: str, metadata: dict[str, str]
    ) -> None:
        del key, content, media_type, metadata
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("concurrent upload was not released")
        raise OSError("late failing upload")


class BlockingSuccessfulObjectStore:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release
        self.calls = 0
        self.objects: dict[str, bytes] = {}

    def put_object(
        self, key: str, content: bytes, media_type: str, metadata: dict[str, str]
    ) -> None:
        del media_type, metadata
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("concurrent upload was not released")
        self.objects[key] = content


@pytest.fixture
def source(session: Session) -> Source:
    source = Source(
        code="final-review",
        name="Final review source",
        connector_type="fixture",
        base_url="fixture.json",
        rights_policy=RightsPolicy.METADATA_ONLY,
    )
    session.add(source)
    session.flush()
    return source


def test_raw_observation_identity_covers_the_complete_harvested_envelope(
    session: Session, source: Source
) -> None:
    """URL, rights, and bytes-only changes are distinct immutable observations."""
    base = HarvestedRecord(
        "oai:final:envelope",
        {"title": "Same metadata"},
        "https://repo.example/items/one",
        "CC BY",
        full_text=b"first bytes",
        media_type="text/plain",
    )
    variants = [
        base,
        HarvestedRecord(
            base.source_identifier,
            base.payload,
            "https://repo.example/items/two",
            base.rights,
            full_text=base.full_text,
            media_type=base.media_type,
        ),
        HarvestedRecord(
            base.source_identifier,
            base.payload,
            base.source_url,
            "CC BY-SA",
            full_text=base.full_text,
            media_type=base.media_type,
        ),
        HarvestedRecord(
            base.source_identifier,
            base.payload,
            base.source_url,
            base.rights,
            full_text=b"second bytes",
            media_type=base.media_type,
        ),
    ]

    results = [
        asyncio.run(harvest_source(session, RecordsConnector([record]), source.id))
        for record in variants
    ]
    recurrence = asyncio.run(harvest_source(session, RecordsConnector([base]), source.id))
    consecutive_retry = asyncio.run(harvest_source(session, RecordsConnector([base]), source.id))

    raw_records = session.scalars(
        select(RawRecord)
        .where(RawRecord.source_identifier == base.source_identifier)
        .order_by(RawRecord.collected_at)
    ).all()
    assert [result.inserted for result in results] == [1, 1, 1, 1]
    assert recurrence.inserted == 1
    assert consecutive_retry.unchanged == 1
    assert len(raw_records) == 5
    assert len({record.checksum for record in raw_records}) == 4
    assert [record.source_url for record in raw_records] == [
        "https://repo.example/items/one",
        "https://repo.example/items/two",
        "https://repo.example/items/one",
        "https://repo.example/items/one",
        "https://repo.example/items/one",
    ]


def test_executable_pipeline_harvests_normalizes_qualifies_and_publishes(
    session: Session, source: Source
) -> None:
    """The public route must be reachable through the audited non-semantic pipeline."""
    record = HarvestedRecord(
        "oai:final:pipeline",
        {
            "title": "Qualified structural metadata",
            "abstract": "A source-provided abstract.",
            "authors": ["Ana Silva"],
        },
        "https://repo.example/items/pipeline",
        "metadata-only",
    )

    first = asyncio.run(
        harvest_normalize_qualify_source(
            session, RecordsConnector([record]), source.id, actor="final-pipeline"
        )
    )
    second = asyncio.run(
        harvest_normalize_qualify_source(
            session, RecordsConnector([record]), source.id, actor="final-pipeline"
        )
    )

    production = session.scalar(select(Production))
    actions = set(session.scalars(select(AuditEvent.action)).all())
    assert first.harvest.inserted == 1
    assert second.harvest.unchanged == 1
    assert production is not None
    assert first.published_production_ids == (production.id,)
    assert production.visibility is RecordVisibility.METADATA_PUBLIC
    assert {"metadata.qualified", "production.visibility_changed"} <= actions


def test_storage_transitions_are_committed_and_audited_with_real_snapshots(
    session: Session, source: Source
) -> None:
    """A restart between upload boundaries must retain an auditable retry state."""
    source.rights_policy = RightsPolicy.OPEN_COPY
    record = HarvestedRecord(
        "oai:final:storage-audit",
        {"title": "Storage audit"},
        "https://repo.example/items/storage-audit",
        "CC BY",
        full_text=b"copyable text",
        media_type="text/plain",
    )

    failed = asyncio.run(
        harvest_source(
            session,
            RecordsConnector([record]),
            source.id,
            actor="final-storage",
            object_store=RecordingObjectStore(error="temporary outage"),
        )
    )
    raw = session.scalar(
        select(RawRecord).where(RawRecord.source_identifier == record.source_identifier)
    )
    assert raw is not None
    association = raw.stored_object
    assert association is not None
    assert failed.status is HarvestStatus.PARTIAL
    assert association.status == "failed"

    recovered_store = RecordingObjectStore()
    recovered = asyncio.run(
        harvest_source(
            session,
            RecordsConnector([record]),
            source.id,
            actor="final-storage",
            object_store=recovered_store,
        )
    )
    session.refresh(association)
    transitions = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == "RawRecordObject",
            AuditEvent.entity_id == association.id,
        )
        .order_by(AuditEvent.timestamp, AuditEvent.id)
    ).all()

    assert recovered.status is HarvestStatus.COMPLETED
    assert association.status == "stored"
    assert [
        (
            event.action,
            event.before and event.before.get("status"),
            event.after and event.after.get("status"),
        )
        for event in transitions
    ] == [
        ("raw_record_object.pending", None, "pending"),
        ("raw_record_object.failed", "pending", "failed"),
        ("raw_record_object.pending", "failed", "pending"),
        ("raw_record_object.stored", "pending", "stored"),
    ]
    snapshots = [event.before for event in transitions if event.before is not None] + [
        event.after for event in transitions if event.after is not None
    ]
    assert all(snapshot is not None and "attempt_started_at" in snapshot for snapshot in snapshots)
    assert transitions[0].after is not None
    assert isinstance(transitions[0].after["attempt_started_at"], str)
    assert transitions[1].before is not None
    assert transitions[1].after is not None
    assert transitions[1].before["attempt_started_at"] == transitions[0].after["attempt_started_at"]
    assert transitions[1].after["attempt_started_at"] is None
    assert transitions[2].before is not None
    assert transitions[2].after is not None
    assert transitions[2].before["attempt_started_at"] is None
    assert isinstance(transitions[2].after["attempt_started_at"], str)
    assert transitions[3].before is not None
    assert transitions[3].after is not None
    assert transitions[3].before["attempt_started_at"] == transitions[2].after["attempt_started_at"]
    assert transitions[3].after["attempt_started_at"] is None
    assert recovered_store.calls == 1


def test_unchanged_replay_cannot_downgrade_a_known_good_stored_object(
    session: Session, source: Source
) -> None:
    """A failed redundant upload must never turn a durable object back into failed."""
    source.rights_policy = RightsPolicy.OPEN_COPY
    record = HarvestedRecord(
        "oai:final:known-good",
        {"title": "Known good"},
        "https://repo.example/items/known-good",
        "CC BY",
        full_text=b"durable text",
        media_type="text/plain",
    )
    asyncio.run(
        harvest_source(
            session,
            RecordsConnector([record]),
            source.id,
            object_store=RecordingObjectStore(),
        )
    )
    raw = session.scalar(
        select(RawRecord).where(RawRecord.source_identifier == record.source_identifier)
    )
    assert raw is not None
    association = raw.stored_object
    assert association is not None

    failing_replay = RecordingObjectStore(error="must not be called")
    replay = asyncio.run(
        harvest_source(
            session,
            RecordsConnector([record]),
            source.id,
            object_store=failing_replay,
        )
    )
    session.refresh(association)

    assert replay.status is HarvestStatus.COMPLETED
    assert replay.unchanged == 1
    assert failing_replay.calls == 0
    assert association.status == "stored"
    assert association.error_summary is None


def test_active_pending_failure_lease_cannot_be_stolen_by_later_success(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'storage-cas.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        source = Source(
            code="storage-cas",
            name="Storage CAS",
            connector_type="fixture",
            rights_policy=RightsPolicy.OPEN_COPY,
        )
        setup.add(source)
        setup.commit()
        source_id = source.id
    record = HarvestedRecord(
        "oai:storage:cas",
        {"title": "Monotonic storage"},
        "https://repo.example/items/storage-cas",
        "CC BY",
        full_text=b"durable bytes",
        media_type="text/plain",
    )
    started = threading.Event()
    release = threading.Event()
    first_result: list[object] = []

    def run_late_failure() -> None:
        with Session(engine) as worker_session:
            first_result.append(
                asyncio.run(
                    harvest_source(
                        worker_session,
                        RecordsConnector([record]),
                        source_id,
                        actor="late-worker",
                        object_store=BlockingFailingObjectStore(started, release),
                    )
                )
            )

    thread = threading.Thread(target=run_late_failure)
    thread.start()
    assert started.wait(timeout=5)
    try:
        with Session(engine) as winning_session:
            winner = asyncio.run(
                harvest_source(
                    winning_session,
                    RecordsConnector([record]),
                    source_id,
                    actor="winning-worker",
                    object_store=RecordingObjectStore(),
                )
            )
    finally:
        release.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    with Session(engine) as verification:
        association = verification.scalar(select(RawRecordObject))
        failed_transitions = verification.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "raw_record_object.failed")
        )
        assert association is not None
        assert association.status == "failed"
        assert association.error_summary == "late failing upload"
        assert association.attempt_token is None
        assert association.attempt_started_at is None
        assert failed_transitions == 1
    assert winner.status is HarvestStatus.COMPLETED
    assert winner.failed == 0
    assert len(first_result) == 1
    assert first_result[0].status is HarvestStatus.PARTIAL
    engine.dispose()


def test_active_pending_storage_lease_cannot_be_stolen_by_later_failure(
    tmp_path: Path,
) -> None:
    """Replacing an active owner would let a newer failure defeat its success."""
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'storage-lease-race.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        source = Source(
            code="storage-lease-race",
            name="Storage lease race",
            connector_type="fixture",
            rights_policy=RightsPolicy.OPEN_COPY,
        )
        setup.add(source)
        setup.commit()
        source_id = source.id
    record = HarvestedRecord(
        "oai:storage:lease-race",
        {"title": "Lease protects the successful upload"},
        "https://repo.example/items/storage-lease-race",
        "CC BY",
        full_text=b"lease-protected bytes",
        media_type="text/plain",
    )
    started = threading.Event()
    release = threading.Event()
    first_result: list[object] = []
    first_store = BlockingSuccessfulObjectStore(started, release)

    def run_successful_upload() -> None:
        with Session(engine) as worker_session:
            first_result.append(
                asyncio.run(
                    harvest_source(
                        worker_session,
                        RecordsConnector([record]),
                        source_id,
                        actor="successful-owner",
                        object_store=first_store,
                    )
                )
            )

    thread = threading.Thread(target=run_successful_upload)
    thread.start()
    assert started.wait(timeout=5)
    failing_store = RecordingObjectStore(error="later worker must not upload")
    try:
        with Session(engine) as competing_session:
            competing = asyncio.run(
                harvest_source(
                    competing_session,
                    RecordsConnector([record]),
                    source_id,
                    actor="competing-failure",
                    object_store=failing_store,
                )
            )
    finally:
        release.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    with Session(engine) as verification:
        association = verification.scalar(select(RawRecordObject))
        failed_transitions = verification.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "raw_record_object.failed")
        )
        assert association is not None
        assert association.status == "stored"
        assert association.attempt_token is None
        assert association.attempt_started_at is None
        assert association.error_summary is None
        assert failed_transitions == 0
    assert competing.status is HarvestStatus.COMPLETED
    assert failing_store.calls == 0
    assert len(first_result) == 1
    assert first_result[0].status is HarvestStatus.COMPLETED
    assert first_store.calls == 1
    engine.dispose()


def test_expired_storage_lease_or_legacy_pending_can_be_reclaimed(session: Session) -> None:
    """Rejecting expired or pre-lease pending rows would strand retryable uploads."""
    source = Source(
        code="expired-storage-lease",
        name="Expired storage lease",
        connector_type="fixture",
        rights_policy=RightsPolicy.OPEN_COPY,
    )
    expired_raw = RawRecord(
        source=source,
        source_identifier="oai:storage:expired-lease",
        payload={"title": "Expired lease"},
        checksum="expired-storage-lease",
    )
    legacy_raw = RawRecord(
        source=source,
        source_identifier="oai:storage:legacy-lease",
        payload={"title": "Legacy lease"},
        checksum="legacy-storage-lease",
    )
    session.add_all(
        [
            expired_raw,
            legacy_raw,
            RawRecordObject(
                raw_record=expired_raw,
                object_key="raw-records/expired/full-text",
                checksum="expired-object",
                media_type="text/plain",
                byte_length=1,
                status="pending",
                attempt_token="expired-owner",
                attempt_started_at=utc_now() - timedelta(minutes=16),
            ),
            RawRecordObject(
                raw_record=legacy_raw,
                object_key="raw-records/legacy/full-text",
                checksum="legacy-object",
                media_type="text/plain",
                byte_length=1,
                status="pending",
                attempt_token="legacy-owner",
                attempt_started_at=None,
            ),
        ]
    )
    session.commit()

    expired = expired_raw.stored_object
    legacy = legacy_raw.stored_object
    assert expired is not None
    assert legacy is not None
    expired_token = _claim_storage_attempt(session, expired.id, actor="lease-recovery")
    legacy_token = _claim_storage_attempt(session, legacy.id, actor="lease-recovery")

    session.refresh(expired)
    session.refresh(legacy)
    assert expired_token is not None
    assert expired_token != "expired-owner"
    assert expired.attempt_token == expired_token
    assert expired.attempt_started_at is not None
    assert legacy_token is not None
    assert legacy_token != "legacy-owner"
    assert legacy.attempt_token == legacy_token
    assert legacy.attempt_started_at is not None


def test_concurrent_storage_association_creation_converges(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'storage-create.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        source = Source(
            code="storage-create",
            name="Storage creation",
            connector_type="fixture",
            rights_policy=RightsPolicy.OPEN_COPY,
        )
        raw = RawRecord(
            source=source,
            source_identifier="oai:storage:create",
            payload={"title": "Association race"},
            checksum="storage-create-checksum",
            state_sequence=1,
        )
        setup.add(raw)
        setup.commit()
        raw_id = raw.id
    record = HarvestedRecord(
        "oai:storage:create",
        {"title": "Association race"},
        "https://repo.example/items/storage-create",
        "CC BY",
        full_text=b"association bytes",
        media_type="text/plain",
    )
    creation_barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def create_association(actor: str) -> None:
        from pci.ingestion.harvest import _store_full_text_for_raw_record

        with Session(engine) as worker_session:
            raw = worker_session.get(RawRecord, raw_id)
            assert raw is not None

            @event.listens_for(worker_session, "before_flush")
            def wait_for_competing_insert(_: Session, __: object, ___: object) -> None:
                if any(isinstance(item, RawRecordObject) for item in worker_session.new):
                    creation_barrier.wait(timeout=5)

            try:
                _store_full_text_for_raw_record(
                    worker_session,
                    raw,
                    record,
                    RightsPolicy.OPEN_COPY,
                    actor,
                    RecordingObjectStore(),
                )
            except Exception as error:  # noqa: BLE001 - asserted concurrency outcome
                errors.append(error)

    threads = [
        threading.Thread(target=create_association, args=(f"creator-{index}",))
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    with Session(engine) as verification:
        associations = verification.scalars(select(RawRecordObject)).all()
        assert len(associations) == 1
        assert associations[0].status == "stored"
    engine.dispose()


def test_pipeline_recovers_an_unchanged_observation_left_before_normalization(
    session: Session, source: Source
) -> None:
    record = HarvestedRecord(
        "oai:continuity:retry",
        {"title": "Recovered after interruption", "abstract": "Durable raw stage."},
        "https://repo.example/items/continuity-retry",
        "metadata-only",
    )
    first_harvest = asyncio.run(harvest_source(session, RecordsConnector([record]), source.id))
    session.commit()

    recovered = asyncio.run(
        harvest_normalize_qualify_source(
            session,
            RecordsConnector([record]),
            source.id,
            actor="continuity-retry",
        )
    )

    assert first_harvest.inserted == 1
    assert recovered.harvest.unchanged == 1
    assert recovered.harvest.observed == 1
    assert len(recovered.normalized_production_ids) == 1
    assert len(recovered.published_production_ids) == 1
    assert session.scalar(select(func.count()).select_from(RawRecord)) == 1
    assert session.scalar(select(func.count()).select_from(ProductionVersion)) == 1


def test_pipeline_reads_large_harvests_in_bounded_database_batches(
    session: Session, source: Source
) -> None:
    records = [
        HarvestedRecord(
            f"oai:batch:{index:03d}",
            {"_oai_pmh": {"header": {"status": "deleted"}}},
            None,
            None,
            is_tombstone=True,
        )
        for index in range(101)
    ]
    select_parameter_counts: list[int] = []
    handoff_queries: list[str] = []

    def capture_selects(
        _: object,
        __: object,
        statement: str,
        parameters: object,
        ___: object,
        ____: object,
    ) -> None:
        if not statement.lstrip().upper().startswith("SELECT"):
            return
        if isinstance(parameters, (dict, tuple)):
            select_parameter_counts.append(len(parameters))
        if "JOIN harvest_observations" in statement:
            handoff_queries.append(statement)

    assert session.bind is not None
    event.listen(session.bind, "before_cursor_execute", capture_selects)
    try:
        result = asyncio.run(
            harvest_normalize_qualify_source(
                session,
                RecordsConnector(records),
                source.id,
                actor="bounded-pipeline",
            )
        )
    finally:
        event.remove(session.bind, "before_cursor_execute", capture_selects)

    assert result.harvest.received == 101
    assert result.harvest.failed == 0
    assert max(select_parameter_counts) <= 100
    assert len(handoff_queries) == 2


def test_pipeline_commits_harvest_before_isolating_a_later_stage_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'durable-pipeline.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        source = Source(
            code="durable-pipeline",
            name="Durable pipeline",
            connector_type="fixture",
            rights_policy=RightsPolicy.METADATA_ONLY,
        )
        setup.add(source)
        setup.commit()
        source_id = source.id
    records = [
        HarvestedRecord(
            "oai:durable:fails-after-normalization",
            {"title": "Rolled back normalized record", "abstract": "Present"},
            "https://repo.example/items/durable-failure",
            "metadata-only",
        ),
        HarvestedRecord(
            "oai:durable:survives",
            {"title": "Independently published record", "abstract": "Present"},
            "https://repo.example/items/durable-success",
            "metadata-only",
        ),
    ]
    original_qualify = ingestion_pipeline.qualify_production

    def fail_first_qualification(
        worker_session: Session,
        production_id: object,
        *,
        actor: str,
    ) -> object:
        version = worker_session.scalar(
            select(ProductionVersion).where(ProductionVersion.production_id == production_id)
        )
        assert version is not None
        raw = worker_session.get(RawRecord, version.raw_record_id)
        assert raw is not None
        if raw.source_identifier == records[0].source_identifier:
            raise RuntimeError("qualification interrupted after normalization")
        return original_qualify(worker_session, production_id, actor=actor)

    monkeypatch.setattr(
        ingestion_pipeline,
        "qualify_production",
        fail_first_qualification,
    )
    with Session(engine) as processing:
        result = asyncio.run(
            harvest_normalize_qualify_source(
                processing,
                RecordsConnector(records),
                source_id,
                actor="durable-boundary",
            )
        )
        processing.rollback()

    with Session(engine) as verification:
        assert verification.scalar(select(func.count()).select_from(HarvestRun)) == 1
        assert verification.scalar(select(func.count()).select_from(RawRecord)) == 2
        assert verification.scalar(select(func.count()).select_from(HarvestObservation)) == 2
        assert verification.scalar(select(func.count()).select_from(ProductionVersion)) == 1
        published = verification.scalar(select(Production))
        assert published is not None
        assert published.visibility is RecordVisibility.METADATA_PUBLIC
        failure_audit = verification.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "ingestion.record_failed",
                AuditEvent.reason == "qualification interrupted after normalization",
            )
        )
        assert failure_audit is not None
    assert result.processing_failed == 1
    assert len(result.normalized_production_ids) == 1
    assert len(result.published_production_ids) == 1
    engine.dispose()


def test_tombstone_never_creates_a_public_orphan(session: Session, source: Source) -> None:
    """A deleted OAI header without earlier metadata is only preserved as provenance."""
    tombstone = HarvestedRecord(
        "oai:final:orphan",
        {"_oai_pmh": {"header": {"status": "deleted"}}},
        None,
        None,
        is_tombstone=True,
    )

    result = asyncio.run(
        harvest_normalize_qualify_source(
            session, RecordsConnector([tombstone]), source.id, actor="final-tombstone"
        )
    )

    raw = session.scalar(
        select(RawRecord).where(RawRecord.source_identifier == tombstone.source_identifier)
    )
    assert raw is not None
    assert raw.is_tombstone is True
    assert result.normalized_production_ids == ()
    assert session.scalar(select(func.count()).select_from(Production)) == 0
    assert (
        session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "raw_record.tombstone_orphaned", AuditEvent.entity_id == raw.id
            )
        )
        is not None
    )


def test_a_historical_payload_reappearing_after_a_change_becomes_current(
    session: Session, source: Source
) -> None:
    first = HarvestedRecord(
        "oai:temporal:aba",
        {"title": "State A", "abstract": "First occurrence."},
        "https://repo.example/items/aba",
        "metadata-only",
    )
    second = HarvestedRecord(
        first.source_identifier,
        {"title": "State B", "abstract": "Intervening state."},
        first.source_url,
        first.rights,
    )

    first_result = asyncio.run(
        harvest_normalize_qualify_source(
            session, RecordsConnector([first]), source.id, actor="temporal-recurrence"
        )
    )
    asyncio.run(
        harvest_normalize_qualify_source(
            session, RecordsConnector([second]), source.id, actor="temporal-recurrence"
        )
    )
    recurrence = asyncio.run(
        harvest_normalize_qualify_source(
            session, RecordsConnector([first]), source.id, actor="temporal-recurrence"
        )
    )
    consecutive_retry = asyncio.run(
        harvest_normalize_qualify_source(
            session, RecordsConnector([first]), source.id, actor="temporal-recurrence"
        )
    )

    production = session.scalar(select(Production))
    assert production is not None
    versions = session.scalars(
        select(ProductionVersion)
        .where(ProductionVersion.production_id == production.id)
        .order_by(ProductionVersion.version)
    ).all()
    assert first_result.harvest.inserted == 1
    assert recurrence.harvest.inserted == 1
    assert consecutive_retry.harvest.unchanged == 1
    assert [(version.version, version.title) for version in versions] == [
        (1, "State A"),
        (2, "State B"),
        (3, "State A"),
    ]
    assert production.current_version_number == 3
