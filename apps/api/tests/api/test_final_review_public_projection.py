import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pci.ingestion.contracts import HarvestedRecord
from pci.ingestion.pipeline import harvest_normalize_qualify_source
from pci.main import create_app
from pci.models.enums import RightsPolicy
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import AuditEvent, RawRecord, Source


class RecordsConnector:
    def __init__(self, records: list[HarvestedRecord]) -> None:
        self.records = records

    async def harvest(self, cursor: str | None) -> AsyncIterator[HarvestedRecord]:
        del cursor
        for record in self.records:
            yield record


class MemoryObjectStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.objects: dict[str, bytes] = {}

    def put_object(
        self, key: str, content: bytes, media_type: str, metadata: dict[str, str]
    ) -> None:
        del media_type, metadata
        if self.fail:
            raise OSError("object-store outage")
        self.objects[key] = content


@pytest.fixture
def source(session: Session) -> Source:
    source = Source(
        code="public-projection",
        name="Public projection source",
        connector_type="fixture",
        rights_policy=RightsPolicy.OPEN_COPY,
    )
    session.add(source)
    session.flush()
    return source


@pytest.fixture
def client(session: Session) -> TestClient:
    app = create_app()
    app.state.session_factory = lambda: session
    with TestClient(app) as test_client:
        yield test_client


def test_live_full_text_projection_recovers_after_a_successful_retry(
    session: Session, source: Source, client: TestClient
) -> None:
    """The immutable version keeps its snapshot while public availability follows storage."""
    record = HarvestedRecord(
        "oai:public:retry",
        {"title": "Retryable full text", "abstract": "Metadata survives storage failure."},
        "https://repo.example/items/retry",
        "CC BY",
        full_text=b"retryable text",
        media_type="text/plain",
    )
    asyncio.run(
        harvest_normalize_qualify_source(
            session,
            RecordsConnector([record]),
            source.id,
            object_store=MemoryObjectStore(fail=True),
        )
    )
    production = session.scalar(select(Production))
    assert production is not None
    initial = client.get(f"/api/v1/productions/{production.id}")
    assert initial.status_code == 200
    assert initial.json()["full_text_available"] is False

    asyncio.run(
        harvest_normalize_qualify_source(
            session,
            RecordsConnector([record]),
            source.id,
            object_store=MemoryObjectStore(),
        )
    )
    version = session.scalar(
        select(ProductionVersion).where(ProductionVersion.production_id == production.id)
    )
    recovered = client.get(f"/api/v1/productions/{production.id}")

    assert version is not None
    assert version.full_text_available is False
    assert recovered.status_code == 200
    assert recovered.json()["full_text_available"] is True


@pytest.mark.parametrize(
    ("published_bytes", "rejected_bytes", "expected_available"),
    [
        (b"published copy", None, True),
        (None, b"rejected copy", False),
    ],
)
def test_rejected_observation_cannot_change_current_public_full_text(
    session: Session,
    source: Source,
    client: TestClient,
    published_bytes: bytes | None,
    rejected_bytes: bytes | None,
    expected_available: bool,
) -> None:
    live = HarvestedRecord(
        "oai:public:qualified-storage",
        {"title": "Qualified storage metadata", "abstract": "Current version."},
        "https://repo.example/items/qualified-storage",
        "CC BY",
        full_text=published_bytes,
        media_type="text/plain" if published_bytes is not None else None,
    )
    asyncio.run(
        harvest_normalize_qualify_source(
            session,
            RecordsConnector([live]),
            source.id,
            object_store=MemoryObjectStore(),
        )
    )
    production = session.scalar(select(Production))
    assert production is not None
    rejected = HarvestedRecord(
        live.source_identifier,
        {"abstract": "Rejected because title is absent."},
        live.source_url,
        live.rights,
        full_text=rejected_bytes,
        media_type="text/plain" if rejected_bytes is not None else None,
    )
    asyncio.run(
        harvest_normalize_qualify_source(
            session,
            RecordsConnector([rejected]),
            source.id,
            object_store=MemoryObjectStore(),
        )
    )

    response = client.get(f"/api/v1/productions/{production.id}")

    assert response.status_code == 200
    assert response.json()["title"] == "Qualified storage metadata"
    assert response.json()["full_text_available"] is expected_available


def test_oai_tombstone_keeps_last_metadata_but_invalidates_public_access(
    session: Session, source: Source, client: TestClient
) -> None:
    """Deleted source records retain valid metadata and immutable tombstone provenance."""
    live = HarvestedRecord(
        "oai:public:deleted",
        {"title": "Withdrawn but citable", "abstract": "Last known valid metadata."},
        "https://repo.example/items/deleted",
        "CC BY",
        full_text=b"last copy",
        media_type="text/plain",
    )
    asyncio.run(
        harvest_normalize_qualify_source(
            session,
            RecordsConnector([live]),
            source.id,
            actor="tombstone-test",
            object_store=MemoryObjectStore(),
        )
    )
    production = session.scalar(select(Production))
    version = session.scalar(select(ProductionVersion))
    assert production is not None
    assert version is not None

    tombstone = HarvestedRecord(
        live.source_identifier,
        {"_oai_pmh": {"header": {"status": "deleted"}}},
        None,
        None,
        is_tombstone=True,
    )
    asyncio.run(
        harvest_normalize_qualify_source(
            session,
            RecordsConnector([tombstone]),
            source.id,
            actor="tombstone-test",
        )
    )
    response = client.get(f"/api/v1/productions/{production.id}")
    tombstone_raw = session.scalar(
        select(RawRecord).where(
            RawRecord.source_identifier == live.source_identifier,
            RawRecord.is_tombstone.is_(True),
        )
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Withdrawn but citable"
    assert response.json()["source"]["source_url"] == "https://repo.example/items/deleted"
    assert response.json()["source"]["access_status"] == "unavailable"
    assert response.json()["full_text_available"] is False
    assert version.raw_record_id != tombstone_raw.id  # type: ignore[union-attr]
    assert session.scalar(select(func.count()).select_from(Production)) == 1
    assert (
        session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "raw_record.tombstoned", AuditEvent.entity_id == production.id
            )
        )
        is not None
    )


def test_identical_live_state_after_a_tombstone_restores_public_access(
    session: Session, source: Source, client: TestClient
) -> None:
    live = HarvestedRecord(
        "oai:public:resurrected",
        {"title": "Resurrected metadata", "abstract": "Same live content."},
        "https://repo.example/items/resurrected",
        "CC BY",
        full_text=b"restored copy",
        media_type="text/plain",
    )
    tombstone = HarvestedRecord(
        live.source_identifier,
        {"_oai_pmh": {"header": {"status": "deleted"}}},
        None,
        None,
        is_tombstone=True,
    )

    asyncio.run(
        harvest_normalize_qualify_source(
            session,
            RecordsConnector([live]),
            source.id,
            actor="resurrection-test",
            object_store=MemoryObjectStore(),
        )
    )
    production = session.scalar(select(Production))
    assert production is not None
    asyncio.run(
        harvest_normalize_qualify_source(
            session,
            RecordsConnector([tombstone]),
            source.id,
            actor="resurrection-test",
        )
    )
    resurrection = asyncio.run(
        harvest_normalize_qualify_source(
            session,
            RecordsConnector([live]),
            source.id,
            actor="resurrection-test",
            object_store=MemoryObjectStore(),
        )
    )

    response = client.get(f"/api/v1/productions/{production.id}")
    versions = session.scalars(
        select(ProductionVersion)
        .where(ProductionVersion.production_id == production.id)
        .order_by(ProductionVersion.version)
    ).all()
    assert resurrection.harvest.inserted == 1
    assert response.status_code == 200
    assert response.json()["title"] == "Resurrected metadata"
    assert response.json()["source"]["access_status"] == "available"
    assert response.json()["full_text_available"] is True
    assert [version.version for version in versions] == [1, 2]


def test_publisher_is_preserved_without_becoming_an_institutional_filter(
    session: Session, source: Source, client: TestClient
) -> None:
    """An OAI dc:publisher is bibliographic metadata, not production affiliation."""
    record = HarvestedRecord(
        "oai:public:publisher",
        {
            "title": "Commercial publisher record",
            "abstract": "Present",
            "publisher": ["Commercial Press"],
        },
        "https://repo.example/items/publisher",
        "metadata-only",
    )
    asyncio.run(harvest_normalize_qualify_source(session, RecordsConnector([record]), source.id))
    production = session.scalar(select(Production))
    assert production is not None

    detail = client.get(f"/api/v1/productions/{production.id}")
    filtered = client.get("/api/v1/productions", params={"institution": "Commercial Press"})

    assert detail.status_code == 200
    assert detail.json()["publishers"] == ["Commercial Press"]
    assert detail.json()["institutions"] == []
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 0
