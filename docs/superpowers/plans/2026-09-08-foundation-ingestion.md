# Foundation and Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the repository foundation and a tested vertical path that collects, preserves, normalizes, deduplicates, stores, and publicly exposes scientific-production metadata.

**Architecture:** Use a Python API and worker service over PostgreSQL as the canonical data store. Source-specific connectors emit one common record contract; raw responses remain immutable, normalized records are versioned, and only qualified metadata reaches the public API.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 17, pgvector, Redis, Dramatiq, MinIO-compatible object storage, pytest, Ruff, mypy, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-08-pernambuco-ciencia-inovacao-design.md`

## Global Constraints

- PostgreSQL is the canonical source; indexes and projections must be reconstructible.
- Preserve every source payload, source identifier, collection timestamp, checksum, and version.
- Never invent missing metadata.
- Metadata may become public after structural quality checks; semantic intelligence remains outside this plan.
- Keep “science produced in Pernambuco” separate from “science about Pernambuco.”
- Store full text only when the rights policy permits it; otherwise retain the source link.
- Public consultation must not require login.
- All writes must be idempotent and auditable.

---

## Repository Map

```text
apps/
  api/
    pyproject.toml
    src/pci/
      main.py
      settings.py
      db.py
      models/
      ingestion/
      normalization/
      productions/
    tests/
  web/                         # created in Plan 3
infra/
  compose.yaml
  postgres/init/001-vector.sql
fixtures/
  repositories/sample-oai.json
docs/superpowers/
  specs/
  plans/
```

### Task 1: Bootstrap the API and local infrastructure

**Files:**
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/src/pci/__init__.py`
- Create: `apps/api/src/pci/main.py`
- Create: `apps/api/src/pci/settings.py`
- Create: `apps/api/tests/test_health.py`
- Create: `infra/compose.yaml`
- Create: `infra/postgres/init/001-vector.sql`
- Create: `.env.example`
- Create: `Makefile`

**Interfaces:**
- Produces: `pci.main.create_app() -> FastAPI`
- Produces: `GET /health -> {"status":"ok"}`
- Produces: environment keys `DATABASE_URL`, `REDIS_URL`, `OBJECT_STORAGE_ENDPOINT`, `OBJECT_STORAGE_BUCKET`

- [ ] **Step 1: Write the failing health test**

```python
# apps/api/tests/test_health.py
from fastapi.testclient import TestClient

from pci.main import create_app


def test_health_returns_ok() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test and verify the initial failure**

Run: `cd apps/api && python -m pytest tests/test_health.py -v`

Expected: FAIL because `pci.main` or `create_app` does not exist.

- [ ] **Step 3: Add the minimal application and development stack**

```python
# apps/api/src/pci/main.py
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Pernambuco Ciência para Inovação", version="0.1.0")

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

Configure `pyproject.toml` with runtime dependencies `fastapi`, `uvicorn`, `pydantic-settings`, `sqlalchemy`, `alembic`, `psycopg[binary]`, `pgvector`, `dramatiq[redis]`, and `boto3`; configure development dependencies `pytest`, `pytest-asyncio`, `httpx`, `pytest-httpx`, `ruff`, and `mypy`. Set the package root to `src` and Python requirement to `>=3.12,<3.13`.

Configure `infra/compose.yaml` with named services `postgres`, `redis`, `minio`, `api`, and `worker`. Expose only development ports, use health checks, and mount `001-vector.sql` containing:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
```

- [ ] **Step 4: Run static and runtime checks**

Run:

```bash
cd apps/api
python -m pytest tests/test_health.py -v
ruff check src tests
mypy src
cd ../..
docker compose -f infra/compose.yaml config --quiet
```

Expected: all commands exit with status 0 and the test reports `1 passed`.

- [ ] **Step 5: Commit the foundation**

```bash
git add .env.example Makefile infra apps/api
git commit -m "chore: bootstrap platform services"
```

### Task 2: Create the canonical provenance and production schema

**Files:**
- Create: `apps/api/src/pci/db.py`
- Create: `apps/api/src/pci/models/base.py`
- Create: `apps/api/src/pci/models/enums.py`
- Create: `apps/api/src/pci/models/provenance.py`
- Create: `apps/api/src/pci/models/production.py`
- Create: `apps/api/src/pci/models/actors.py`
- Create: `apps/api/src/pci/models/territory.py`
- Create: `apps/api/alembic.ini`
- Create: `apps/api/alembic/env.py`
- Create: `apps/api/alembic/versions/0001_core_metadata.py`
- Create: `apps/api/tests/models/test_core_schema.py`

**Interfaces:**
- Produces: `pci.db.session_scope() -> Iterator[Session]`
- Produces models: `Source`, `HarvestRun`, `RawRecord`, `Production`, `ProductionVersion`, `Person`, `Organization`, `Authorship`, `Territory`, `ProductionTerritory`, `AuditEvent`
- Produces enums: `ProductionType`, `TerritoryRelation`, `RecordVisibility`, `HarvestStatus`

- [ ] **Step 1: Write failing schema and constraint tests**

```python
# apps/api/tests/models/test_core_schema.py
from sqlalchemy.exc import IntegrityError

from pci.models.production import Production, ProductionVersion
from pci.models.provenance import RawRecord, Source


def test_raw_record_is_unique_per_source_identifier_and_checksum(session) -> None:
    source = Source(code="fixture", name="Fixture Repository", connector_type="fixture")
    session.add(source)
    session.flush()
    record = dict(
        source_id=source.id,
        source_identifier="oai:fixture:1",
        checksum="abc123",
        payload={"title": "A"},
    )
    session.add(RawRecord(**record))
    session.commit()
    session.add(RawRecord(**record))
    with pytest.raises(IntegrityError):
        session.commit()


def test_production_version_never_overwrites_prior_version(session) -> None:
    production = Production(canonical_key="doi:10.1/example")
    session.add(production)
    session.flush()
    session.add_all([
        ProductionVersion(production_id=production.id, version=1, title="First"),
        ProductionVersion(production_id=production.id, version=2, title="Corrected"),
    ])
    session.commit()
    versions = session.query(ProductionVersion).order_by(ProductionVersion.version).all()
    assert [item.title for item in versions] == ["First", "Corrected"]
```

Add `import pytest` at the top and provide the transactional `session` fixture in `apps/api/tests/conftest.py` using a dedicated PostgreSQL test database.

- [ ] **Step 2: Run the model tests and confirm failure**

Run: `cd apps/api && python -m pytest tests/models/test_core_schema.py -v`

Expected: FAIL because the models and migration do not exist.

- [ ] **Step 3: Implement the schema and first migration**

Use UUID primary keys and timezone-aware timestamps. Define these mandatory columns and constraints:

```python
# apps/api/src/pci/models/enums.py
from enum import StrEnum


class TerritoryRelation(StrEnum):
    PRODUCED_IN_PE = "produced_in_pe"
    ABOUT_PE = "about_pe"


class RecordVisibility(StrEnum):
    PRIVATE = "private"
    METADATA_PUBLIC = "metadata_public"


class ProductionType(StrEnum):
    ARTICLE = "article"
    THESIS = "thesis"
    DISSERTATION = "dissertation"
    UNDERGRADUATE_WORK = "undergraduate_work"
    BOOK = "book"
    BOOK_CHAPTER = "book_chapter"
    CONFERENCE_PAPER = "conference_paper"
    TECHNICAL_REPORT = "technical_report"
    RESEARCH_PROJECT = "research_project"
    PATENT = "patent"
    SOFTWARE = "software"
    DATASET = "dataset"
    PROTOCOL = "protocol"
    METHOD = "method"
    PROCESS = "process"
    SOCIAL_TECHNOLOGY = "social_technology"
    EDUCATIONAL_PRODUCT = "educational_product"
    TECHNICAL_PRODUCT = "technical_product"
    OTHER = "other"
```

`Source` stores `code`, `name`, `connector_type`, `base_url`, `rights_policy`, `active`, and `schedule`. `HarvestRun` stores source, start/end timestamps, cursor, status, counts, and error summary. `RawRecord` stores source, source identifier, immutable JSON payload, SHA-256 checksum, collected time, rights snapshot, and harvest run; enforce a unique constraint on `(source_id, source_identifier, checksum)`.

`Production` stores a stable canonical key, current version number, visibility, creation time, and update time. `ProductionVersion` stores version number, title, abstract, publication date, language, type, identifiers JSON, keywords JSON, source URL, full-text availability, rights, and normalization report; enforce `(production_id, version)` uniqueness.

`ProductionTerritory` must store `production_id`, `territory_id`, and `relation`, allowing the same production to carry both territorial relations. `AuditEvent` stores actor, action, entity type, entity ID, before JSON, after JSON, reason, and timestamp.

- [ ] **Step 4: Apply migrations and run integrity checks**

Run:

```bash
cd apps/api
alembic upgrade head
python -m pytest tests/models/test_core_schema.py -v
ruff check src tests
mypy src
```

Expected: migration succeeds; schema tests pass; lint and type checks exit 0.

- [ ] **Step 5: Commit the canonical model**

```bash
git add apps/api
git commit -m "feat: add canonical metadata schema"
```

### Task 3: Implement the connector contract and immutable harvesting

**Files:**
- Create: `apps/api/src/pci/ingestion/contracts.py`
- Create: `apps/api/src/pci/ingestion/connectors/base.py`
- Create: `apps/api/src/pci/ingestion/connectors/fixture.py`
- Create: `apps/api/src/pci/ingestion/connectors/oai_pmh.py`
- Create: `apps/api/src/pci/ingestion/harvest.py`
- Create: `apps/api/src/pci/ingestion/tasks.py`
- Create: `apps/api/src/pci/storage/objects.py`
- Create: `fixtures/repositories/sample-oai.json`
- Create: `apps/api/tests/ingestion/test_fixture_connector.py`
- Create: `apps/api/tests/ingestion/test_oai_pmh_connector.py`
- Create: `apps/api/tests/ingestion/test_harvest_idempotency.py`
- Create: `apps/api/tests/storage/test_rights_gate.py`

**Interfaces:**
- Produces: `HarvestedRecord(source_identifier: str, payload: dict[str, Any], source_url: str | None, rights: str | None)`
- Produces: `SourceConnector.harvest(cursor: str | None) -> AsyncIterator[HarvestedRecord]`
- Produces: `harvest_source(session: Session, connector: SourceConnector, source_id: UUID) -> HarvestResult`
- Produces: `HarvestResult(run_id: UUID, status: HarvestStatus, received: int, inserted: int, unchanged: int, failed: int)`
- Produces: `RightsPolicy` with values `METADATA_ONLY`, `LINK_ONLY`, `OPEN_COPY`, and `INSTITUTION_AUTHORIZED_COPY`
- Produces: `store_full_text_if_permitted(record: HarvestedRecord, policy: RightsPolicy) -> StoredObject | None`

- [ ] **Step 1: Write failing connector and idempotency tests**

```python
import asyncio


async def test_fixture_connector_emits_common_contract() -> None:
    connector = FixtureConnector(Path("../../fixtures/repositories/sample-oai.json"))
    records = [record async for record in connector.harvest(cursor=None)]
    assert records[0].source_identifier == "oai:sample:1"
    assert records[0].payload["title"] == "Tecnologia social para saneamento rural"


def test_harvesting_same_payload_twice_is_idempotent(session, fixture_connector, source) -> None:
    first = asyncio.run(harvest_source(session, fixture_connector, source.id))
    second = asyncio.run(harvest_source(session, fixture_connector, source.id))
    assert first.inserted == 2
    assert second.inserted == 0
    assert second.unchanged == 2


async def test_oai_connector_follows_resumption_token(httpx_mock) -> None:
    httpx_mock.add_response(text=first_oai_page_with_token("next-page"))
    httpx_mock.add_response(text=second_oai_page_without_token())
    records = [record async for record in OaiPmhConnector("https://repo.example/oai").harvest(None)]
    assert [record.source_identifier for record in records] == ["oai:repo:1", "oai:repo:2"]


def test_full_text_is_not_stored_without_permission(object_store, harvested_record) -> None:
    stored = store_full_text_if_permitted(harvested_record, RightsPolicy.METADATA_ONLY)
    assert stored is None
    assert object_store.keys() == []
```

Define `first_oai_page_with_token()` and `second_oai_page_without_token()` in the OAI test module with literal `OAI-PMH`, `ListRecords`, Dublin Core, and `resumptionToken` XML so the pagination test is independent of a live repository.

- [ ] **Step 2: Run ingestion tests and confirm failure**

Run: `cd apps/api && python -m pytest tests/ingestion -v`

Expected: FAIL because connector contracts and harvest functions are undefined.

- [ ] **Step 3: Implement the connector boundary and raw-record writer**

```python
# apps/api/src/pci/ingestion/connectors/base.py
from collections.abc import AsyncIterator
from typing import Protocol

from pci.ingestion.contracts import HarvestedRecord


class SourceConnector(Protocol):
    async def harvest(self, cursor: str | None) -> AsyncIterator[HarvestedRecord]: ...
```

Compute the checksum from canonical JSON using sorted keys and UTF-8. On repeated `(source, identifier, checksum)`, count the record as unchanged. On a new checksum for an existing source identifier, insert a new immutable `RawRecord`. Wrap each run in `HarvestRun`; a record-level failure increments `failed` without deleting successful records. The Dramatiq actor accepts `source_id: str`, resolves the configured connector, and invokes the same service used by tests.

The fixture must contain two records, including title, abstract, authors, institution, date, type, identifiers, rights, source URL, and one missing optional field to verify that absence is preserved.

Implement a generic OAI-PMH connector for `ListRecords` with configurable metadata prefix, resumption-token pagination, timeout, bounded retry for transient errors, and XML namespace handling. It must emit the common contract and retain unmapped Dublin Core fields inside the original payload.

Implement a rights gate with closed policies `metadata_only`, `link_only`, `open_copy`, and `institution_authorized_copy`. Only the final two may write full-text bytes to object storage. Store checksum, media type, byte length, rights snapshot, and source URL with each permitted object; never fetch or copy full text when the policy is unknown.

- [ ] **Step 4: Verify idempotency and worker serialization**

Run:

```bash
cd apps/api
python -m pytest tests/ingestion tests/storage -v
ruff check src tests
mypy src
```

Expected: all tests pass; running the fixture twice inserts no duplicate raw payload; OAI pagination returns both records; metadata-only content creates no stored object.

- [ ] **Step 5: Commit ingestion**

```bash
git add apps/api fixtures
git commit -m "feat: preserve source records through connector contract"
```

### Task 4: Normalize metadata and perform conservative deduplication

**Files:**
- Create: `apps/api/src/pci/normalization/contracts.py`
- Create: `apps/api/src/pci/normalization/text.py`
- Create: `apps/api/src/pci/normalization/identifiers.py`
- Create: `apps/api/src/pci/normalization/records.py`
- Create: `apps/api/src/pci/normalization/deduplication.py`
- Create: `apps/api/src/pci/normalization/service.py`
- Create: `apps/api/tests/normalization/test_normalize_record.py`
- Create: `apps/api/tests/normalization/test_deduplication.py`

**Interfaces:**
- Produces: `NormalizedRecord`
- Produces: `normalize_record(raw: HarvestedRecord) -> NormalizedRecord`
- Produces: `match_production(session: Session, record: NormalizedRecord) -> MatchDecision`
- Produces: `MatchDecision(kind: Literal["new","exact","review"], production_id: UUID | None, reasons: tuple[str, ...])`
- Produces: `persist_normalized_record(session: Session, raw_record_id: UUID) -> UUID`

- [ ] **Step 1: Write failing normalization and matching tests**

```python
def test_normalize_record_preserves_original_and_cleans_identifiers() -> None:
    record = normalize_record(harvested_record(
        title="  Água\u00a0e inovação  ",
        doi="HTTPS://DOI.ORG/10.1000/ABC",
    ))
    assert record.title == "Água e inovação"
    assert record.identifiers["doi"] == "10.1000/abc"
    assert record.missing_fields == ("abstract",)


def test_exact_doi_matches_but_title_similarity_requires_review(session) -> None:
    existing = persist_production(session, doi="10.1000/abc", title="Água e inovação")
    assert match_production(session, normalized_record(doi="10.1000/ABC")).kind == "exact"
    ambiguous = match_production(session, normalized_record(title="Agua e inovacao"))
    assert ambiguous.kind == "review"
    assert ambiguous.production_id == existing.id
```

- [ ] **Step 2: Run normalization tests and confirm failure**

Run: `cd apps/api && python -m pytest tests/normalization -v`

Expected: FAIL because the normalization and matching functions do not exist.

- [ ] **Step 3: Implement deterministic normalization and conservative matching**

Normalize whitespace and Unicode for display without removing accents from canonical display values. Normalize DOI, ORCID, ISBN, patent number, repository handle, and URL into dedicated identifier keys. Record every transformation and every missing source field in `normalization_report`.

Use these matching rules in order:

1. exact normalized DOI, patent number, handle, or source-stable identifier: `exact`;
2. exact title plus publication year plus at least one normalized author: `exact`;
3. title trigram similarity at least `0.90` with compatible year or author: `review`;
4. otherwise: `new`.

Never automatically merge a `review` decision. Persist it in a `DuplicateCandidate` table added by migration `0002_duplicate_candidates.py`, with score, reasons, status, and reviewer fields.

- [ ] **Step 4: Verify normalization, matching, and version creation**

Run:

```bash
cd apps/api
alembic upgrade head
python -m pytest tests/normalization -v
python -m pytest tests/models tests/ingestion -v
ruff check src tests
mypy src
```

Expected: all tests pass; an updated source payload creates a new `ProductionVersion`; ambiguous matches remain unmerged.

- [ ] **Step 5: Commit normalization**

```bash
git add apps/api
git commit -m "feat: normalize and conservatively deduplicate metadata"
```

### Task 5: Publish the metadata-only public API

**Files:**
- Create: `apps/api/src/pci/productions/schemas.py`
- Create: `apps/api/src/pci/productions/repository.py`
- Create: `apps/api/src/pci/productions/service.py`
- Create: `apps/api/src/pci/productions/router.py`
- Modify: `apps/api/src/pci/main.py`
- Create: `apps/api/tests/api/test_public_productions.py`
- Create: `apps/api/tests/api/test_metadata_visibility.py`

**Interfaces:**
- Produces: `GET /api/v1/productions`
- Produces: `GET /api/v1/productions/{production_id}`
- Produces: `PublicProductionSummary` and `PublicProductionDetail`
- Consumes: canonical `Production`, current `ProductionVersion`, actor, institution, source, and territory relations

- [ ] **Step 1: Write failing public API tests**

```python
def test_public_list_returns_only_metadata_public_records(client, productions) -> None:
    response = client.get("/api/v1/productions?territory_relation=produced_in_pe")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    item = response.json()["items"][0]
    assert item["title"] == "Tecnologia social para saneamento rural"
    assert item["territory_relations"] == ["produced_in_pe"]
    assert "semantic_assertions" not in item


def test_public_detail_exposes_provenance_and_missing_fields(client, public_production) -> None:
    response = client.get(f"/api/v1/productions/{public_production.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["source"]["name"] == "Fixture Repository"
    assert body["source"]["source_url"].startswith("https://")
    assert body["quality"]["missing_fields"] == ["abstract"]
```

- [ ] **Step 2: Run API tests and confirm failure**

Run: `cd apps/api && python -m pytest tests/api -v`

Expected: FAIL with 404 or missing router/schema errors.

- [ ] **Step 3: Implement metadata schemas, query service, and router**

Support pagination and exact filters for institution, production type, publication year, and territorial relation. Return the current version only, plus provenance and an explicit quality object. Do not add semantic fields to either response model. If a source link is unavailable, return `access_status: "unavailable"` rather than omitting provenance.

Register the router:

```python
from pci.productions.router import router as productions_router

app.include_router(productions_router, prefix="/api/v1")
```

- [ ] **Step 4: Run the complete Plan 1 verification suite**

Run:

```bash
docker compose -f infra/compose.yaml up -d postgres redis minio
cd apps/api
alembic upgrade head
python -m pytest -v
ruff check src tests
mypy src
```

Expected: all tests pass; public endpoints require no authorization; no semantic draft or internal audit field appears in serialized responses.

- [ ] **Step 5: Commit the first vertical slice**

```bash
git add apps/api
git commit -m "feat: expose qualified public metadata"
```

## Plan 1 Completion Gate

- A fixture source can be harvested twice without duplicate writes.
- Raw payloads and normalized versions are independently inspectable.
- The generic OAI-PMH connector handles resumption-token pagination through the common contract.
- The rights gate prevents full-text copying unless an explicit policy permits it.
- The two territorial relations can coexist on one production.
- Ambiguous duplicates enter a review queue instead of merging.
- Public endpoints expose metadata and provenance without semantic intelligence.
- Migrations, tests, lint, and type checks pass from a clean database.
