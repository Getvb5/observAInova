import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pci.ingestion.connectors.fixture import FixtureConnector
from pci.ingestion.contracts import HarvestedRecord
from pci.ingestion.harvest import canonical_harvested_record_checksum, harvest_source
from pci.models.enums import HarvestStatus, RightsPolicy
from pci.models.provenance import AuditEvent, HarvestRun, RawRecord, Source

FIXTURE_PATH = Path(__file__).parents[4] / "fixtures/repositories/sample-oai.json"


class RecordsConnector:
    def __init__(self, records: list[HarvestedRecord], *, flow_error: str | None = None) -> None:
        self.records = records
        self.flow_error = flow_error

    async def harvest(self, cursor: str | None) -> AsyncIterator[HarvestedRecord]:
        del cursor
        for record in self.records:
            yield record
        if self.flow_error is not None:
            raise RuntimeError(self.flow_error)


class RecordingObjectStore:
    def __init__(self, *, error: str | None = None) -> None:
        self.error = error
        self.objects: dict[str, bytes] = {}

    def put_object(
        self, key: str, content: bytes, media_type: str, metadata: dict[str, str]
    ) -> None:
        del media_type, metadata
        if self.error is not None:
            raise OSError(self.error)
        self.objects[key] = content


@pytest.fixture
def source(session: Session) -> Source:
    source = Source(
        code="sample",
        name="Sample repository",
        connector_type="fixture",
        base_url=str(FIXTURE_PATH),
        rights_policy=RightsPolicy.METADATA_ONLY,
    )
    session.add(source)
    session.flush()
    return source


def test_harvesting_same_payload_twice_is_idempotent(session: Session, source: Source) -> None:
    """Removing checksum identity must insert duplicate immutable raw records."""
    first = asyncio.run(harvest_source(session, FixtureConnector(FIXTURE_PATH), source.id))
    second = asyncio.run(harvest_source(session, FixtureConnector(FIXTURE_PATH), source.id))

    assert first.inserted == 2
    assert first.status is HarvestStatus.COMPLETED
    assert second.inserted == 0
    assert second.unchanged == 2
    assert session.scalar(select(func.count()).select_from(RawRecord)) == 2


def test_metadata_only_raw_record_preserves_source_url(session: Session, source: Source) -> None:
    """Skipping full-text storage must not discard the canonical record URL."""
    record = HarvestedRecord(
        "oai:sample:url",
        {"title": "Source URL"},
        "https://repo.example/items/source-url",
        "metadata only",
    )

    asyncio.run(harvest_source(session, RecordsConnector([record]), source.id))

    raw = session.scalar(
        select(RawRecord).where(RawRecord.source_identifier == "oai:sample:url")
    )
    assert raw is not None
    assert raw.source_url == "https://repo.example/items/source-url"


def test_changed_payload_creates_a_new_immutable_raw_record(session: Session, source: Source) -> None:
    """Comparing only source identifiers must hide a changed source payload."""
    first = HarvestedRecord("oai:sample:changed", {"title": "A"}, None, None)
    changed = HarvestedRecord("oai:sample:changed", {"title": "B"}, None, None)

    asyncio.run(harvest_source(session, RecordsConnector([first]), source.id))
    result = asyncio.run(harvest_source(session, RecordsConnector([changed]), source.id))

    payloads = session.scalars(
        select(RawRecord.payload).where(RawRecord.source_identifier == "oai:sample:changed")
    ).all()
    assert result.inserted == 1
    assert payloads == [{"title": "A"}, {"title": "B"}]


def test_record_failure_preserves_successful_records(session: Session, source: Source) -> None:
    """Letting one malformed payload abort the run must erase the prior success."""
    valid = HarvestedRecord("oai:sample:valid", {"title": "Valid"}, None, None)
    invalid = HarvestedRecord("oai:sample:invalid", {"bad": {"not-json"}}, None, None)

    result = asyncio.run(harvest_source(session, RecordsConnector([valid, invalid]), source.id))

    assert result.status is HarvestStatus.PARTIAL
    assert result.received == 2
    assert result.inserted == 1
    assert result.failed == 1
    assert session.scalar(select(func.count()).select_from(RawRecord)) == 1


def test_flow_failure_closes_run_and_audits_state(session: Session, source: Source) -> None:
    """Propagating a stream error must leave a running, unaudited harvest behind."""
    valid = HarvestedRecord("oai:sample:before-error", {"title": "Valid"}, None, None)

    result = asyncio.run(
        harvest_source(
            session,
            RecordsConnector([valid], flow_error="repository unavailable"),
            source.id,
            actor="ingestion-test",
        )
    )

    run = session.get(HarvestRun, result.run_id)
    raw = session.scalar(
        select(RawRecord).where(RawRecord.source_identifier == "oai:sample:before-error")
    )
    actions = session.scalars(
        select(AuditEvent.action).where(AuditEvent.actor == "ingestion-test")
    ).all()
    assert result.status is HarvestStatus.FAILED
    assert result.inserted == 1
    assert result.failed == 1
    assert run is not None
    assert run.ended_at is not None
    assert run.error_summary == "repository unavailable"
    assert raw is not None
    assert actions == [
        "harvest_run.started",
        "raw_record.created",
        "harvest_observation.created",
        "harvest_run.status_changed",
    ]


def test_unique_race_is_classified_as_unchanged(
    session: Session,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent insert of the same identity must not make the run partial."""
    record = HarvestedRecord("oai:sample:race", {"title": "Same"}, None, None)
    existing = RawRecord(
        source_id=source.id,
        source_identifier="oai:sample:race",
        payload={"title": "Same"},
        checksum=canonical_harvested_record_checksum(record),
    )
    session.add(existing)
    session.flush()
    real_scalar = session.scalar
    first_lookup = True

    def miss_first_identity_lookup(statement, *args, **kwargs):
        nonlocal first_lookup
        if first_lookup:
            first_lookup = False
            return None
        return real_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(session, "scalar", miss_first_identity_lookup)
    result = asyncio.run(harvest_source(session, RecordsConnector([record]), source.id))

    assert result.status is HarvestStatus.COMPLETED
    assert result.inserted == 0
    assert result.unchanged == 1
    assert result.failed == 0
    assert real_scalar(select(func.count()).select_from(RawRecord)) == 1


def test_upload_failure_preserves_raw_and_reconciles_same_association(
    session: Session, source: Source
) -> None:
    """An upload failure must leave one retryable association without deleting raw data."""
    source.rights_policy = RightsPolicy.OPEN_COPY
    session.flush()
    record = HarvestedRecord(
        "oai:sample:full-text",
        {"title": "Full text"},
        "https://repo.example/items/full-text",
        "Cópia autorizada",
        full_text=b"same bytes",
        media_type="text/plain",
    )

    failed = asyncio.run(
        harvest_source(
            session,
            RecordsConnector([record]),
            source.id,
            actor="storage-test",
            object_store=RecordingObjectStore(error="storage unavailable"),
        )
    )

    raw = session.scalar(
        select(RawRecord).where(RawRecord.source_identifier == "oai:sample:full-text")
    )
    assert failed.status is HarvestStatus.PARTIAL
    assert failed.inserted == 1
    assert failed.failed == 1
    assert raw is not None
    assert raw.source_url == "https://repo.example/items/full-text"
    assert raw.stored_object is not None
    assert raw.stored_object.status == "failed"
    assert raw.stored_object.error_summary == "storage unavailable"
    object_key = raw.stored_object.object_key
    assert str(raw.id) in object_key

    recovered_store = RecordingObjectStore()
    recovered = asyncio.run(
        harvest_source(
            session,
            RecordsConnector([record]),
            source.id,
            actor="storage-test",
            object_store=recovered_store,
        )
    )

    session.refresh(raw.stored_object)
    actions = session.scalars(
        select(AuditEvent.action).where(AuditEvent.actor == "storage-test")
    ).all()
    assert recovered.status is HarvestStatus.COMPLETED
    assert recovered.inserted == 0
    assert recovered.unchanged == 1
    assert recovered.failed == 0
    assert raw.stored_object.status == "stored"
    assert raw.stored_object.error_summary is None
    assert recovered_store.objects == {object_key: b"same bytes"}
    assert actions.count("raw_record_object.failed") == 1
    assert actions.count("raw_record_object.stored") == 1

    repeat_store = RecordingObjectStore()
    repeated = asyncio.run(
        harvest_source(
            session,
            RecordsConnector([record]),
            source.id,
            actor="storage-test",
            object_store=repeat_store,
        )
    )
    assert repeated.status is HarvestStatus.COMPLETED
    assert repeated.unchanged == 1
    assert repeat_store.objects == {}


def test_content_changed_after_a_failed_upload_creates_a_new_immutable_raw_observation(
    session: Session, source: Source
) -> None:
    """Changed content must never be forced through the prior raw observation's descriptor."""
    source.rights_policy = RightsPolicy.OPEN_COPY
    session.flush()
    first = HarvestedRecord(
        "oai:sample:descriptor",
        {"title": "Same metadata"},
        "https://repo.example/items/descriptor",
        "Cópia autorizada",
        full_text=b"first bytes",
        media_type="text/plain",
    )
    changed = HarvestedRecord(
        "oai:sample:descriptor",
        {"title": "Same metadata"},
        "https://repo.example/items/descriptor",
        "Cópia autorizada",
        full_text=b"different bytes",
        media_type="text/plain",
    )

    asyncio.run(
        harvest_source(
            session,
            RecordsConnector([first]),
            source.id,
            actor="descriptor-test",
            object_store=RecordingObjectStore(error="initial failure"),
        )
    )
    raw = session.scalar(
        select(RawRecord).where(RawRecord.source_identifier == "oai:sample:descriptor")
    )
    assert raw is not None
    assert raw.stored_object is not None
    association_id = raw.stored_object.id

    incompatible_store = RecordingObjectStore()
    result = asyncio.run(
        harvest_source(
            session,
            RecordsConnector([changed]),
            source.id,
            actor="descriptor-test",
            object_store=incompatible_store,
        )
    )

    session.refresh(raw.stored_object)
    observations = session.scalars(
        select(RawRecord)
        .where(RawRecord.source_identifier == "oai:sample:descriptor")
        .order_by(RawRecord.collected_at)
    ).all()
    assert result.status is HarvestStatus.COMPLETED
    assert result.inserted == 1
    assert result.unchanged == 0
    assert result.failed == 0
    assert len(incompatible_store.objects) == 1
    assert raw.stored_object.id == association_id
    assert raw.stored_object.status == "failed"
    assert raw.stored_object.checksum == (
        "d67e08ade6e823c063affb00fea95adabffa75cf1a660d8fcea3223d68e8e44d"
    )
    assert raw.stored_object.byte_length == 11
    assert len(observations) == 2
    assert observations[1].stored_object is not None
    assert observations[1].stored_object.status == "stored"
    assert observations[1].stored_object.checksum != raw.stored_object.checksum
