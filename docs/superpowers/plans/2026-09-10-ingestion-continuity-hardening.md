# Ingestion Continuity Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the ingestion pipeline recover durably harvested observations, preserve legacy production continuity through immutable provenance, and expose full-text availability only for the currently published version.

**Architecture:** Extend the harvest result with the raw observation IDs actually encountered, then make the pipeline consume that explicit hand-off instead of inferring work from the creation run. Resolve source continuity through existing `ProductionVersion → RawRecord` provenance before identifier matching. Split public storage state into current-version object availability and a separate later-tombstone invalidation flag.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Pydantic 2, Pytest, Ruff, mypy, Alembic, PostgreSQL production target with SQLite dialect-neutral tests.

**Spec:** `docs/superpowers/specs/2026-09-10-ingestion-continuity-hardening-design.md`

## Global Constraints

- Raw observations and normalized versions remain immutable and independently inspectable.
- Reprocessing must be idempotent through the existing `ProductionVersion.raw_record_id` uniqueness boundary.
- Structural qualification may publish metadata only; semantic intelligence remains outside this plan.
- Ambiguous provenance must be rejected and audited rather than guessed or merged.
- Historical `Production.canonical_key` values are not rewritten.
- Author affiliation, producing institution, publisher, and territorial relation remain distinct concepts.
- Public responses must expose only `metadata_public` records and must not leak raw payloads, audit events, duplicate candidates, or semantic drafts.
- A tombstone invalidates access separately and does not replace the last valid bibliographic metadata.
- Every state-changing service write remains auditable.
- Docker, live PostgreSQL, Redis, and MinIO are unavailable in this environment; offline PostgreSQL DDL and dialect-neutral tests do not constitute live integration proof.

---

### Task 1: Hand encountered raw observations from harvesting to the pipeline

**Files:**
- Modify: `apps/api/src/pci/ingestion/contracts.py`
- Modify: `apps/api/src/pci/ingestion/harvest.py`
- Modify: `apps/api/src/pci/ingestion/pipeline.py`
- Modify: `apps/api/tests/ingestion/test_final_review_ingestion.py`

**Interfaces:**
- Consumes: `_persist_raw_record(session, run, record, actor) -> tuple[RawRecord, bool]`
- Produces: `HarvestResult.observed_raw_record_ids: tuple[uuid.UUID, ...]`
- Produces: `harvest_normalize_qualify_source(...)` processes both inserted and unchanged observations returned by the harvest

- [ ] **Step 1: Write the failing retry test**

Append a test that persists the raw stage first, commits that boundary, and then reruns the complete pipeline with the identical observation:

```python
def test_pipeline_recovers_an_unchanged_observation_left_before_normalization(
    session: Session, source: Source
) -> None:
    record = HarvestedRecord(
        "oai:continuity:retry",
        {"title": "Recovered after interruption", "abstract": "Durable raw stage."},
        "https://repo.example/items/continuity-retry",
        "metadata-only",
    )
    first_harvest = asyncio.run(
        harvest_source(session, RecordsConnector([record]), source.id)
    )
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
    assert len(recovered.harvest.observed_raw_record_ids) == 1
    assert len(recovered.normalized_production_ids) == 1
    assert len(recovered.published_production_ids) == 1
    assert session.scalar(select(func.count()).select_from(RawRecord)) == 1
    assert session.scalar(select(func.count()).select_from(ProductionVersion)) == 1
```

- [ ] **Step 2: Run the retry test and verify RED**

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m pytest tests/ingestion/test_final_review_ingestion.py::test_pipeline_recovers_an_unchanged_observation_left_before_normalization -v
```

Expected: FAIL because `HarvestResult` has no `observed_raw_record_ids` and the replay pipeline selects only `RawRecord.harvest_run_id == recovered.harvest.run_id`.

- [ ] **Step 3: Extend the harvest result without breaking existing constructors**

Add the field after the existing counters:

```python
@dataclass(frozen=True, slots=True)
class HarvestResult:
    run_id: uuid.UUID
    status: HarvestStatus
    received: int
    inserted: int
    unchanged: int
    failed: int
    observed_raw_record_ids: tuple[uuid.UUID, ...] = ()
```

In `harvest_source`, initialize `observed_raw_record_ids: list[uuid.UUID] = []`, append `raw_record.id` immediately after every successful `_persist_raw_record(...)` call regardless of its `inserted` flag, and return:

```python
observed_raw_record_ids=tuple(dict.fromkeys(observed_raw_record_ids))
```

- [ ] **Step 4: Consume the explicit observation hand-off in pipeline order**

Replace the `harvest_run_id` query with an ID lookup that preserves `HarvestResult` order:

```python
observed_ids = harvest.observed_raw_record_ids
raw_by_id = {
    raw.id: raw
    for raw in session.scalars(
        select(RawRecord).where(RawRecord.id.in_(observed_ids))
    ).all()
} if observed_ids else {}
raw_records = [raw_by_id[raw_id] for raw_id in observed_ids if raw_id in raw_by_id]
```

Keep the existing per-record normalization rejection, qualification, tombstone handling, and de-duplication of returned production IDs.

- [ ] **Step 5: Verify recovery and idempotency**

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m pytest tests/ingestion/test_final_review_ingestion.py -v
python -m pytest tests/ingestion/test_harvest_idempotency.py -v
```

Expected: all ingestion tests PASS; an identical replay processes the existing observation without creating a raw record or production version.

- [ ] **Step 6: Commit Task 1**

```bash
git add apps/api/src/pci/ingestion/contracts.py apps/api/src/pci/ingestion/harvest.py apps/api/src/pci/ingestion/pipeline.py apps/api/tests/ingestion/test_final_review_ingestion.py
git commit -m "fix: recover unfinished raw observations"
```

---

### Task 2: Resolve legacy production continuity through immutable provenance

**Files:**
- Modify: `apps/api/src/pci/normalization/service.py`
- Modify: `apps/api/tests/normalization/test_final_review_normalization.py`

**Interfaces:**
- Consumes: `RawRecord.source_id`, `RawRecord.source_identifier`, and existing `ProductionVersion.raw_record_id`
- Produces: `_production_for_source_provenance(session, raw) -> Production | None`
- Preserves: the existing `Production.canonical_key`; only new productions use the UUID-scoped source identifier

- [ ] **Step 1: Write failing legacy continuity tests**

Add one test for the unique-provenance path and one for the ambiguous-provenance rejection:

```python
def test_legacy_source_key_advances_the_same_production_through_raw_provenance(
    session: Session,
) -> None:
    source = _source(session, "legacy-source")
    first_raw = _raw(
        session,
        source,
        "oai:legacy:one",
        {"title": "Legacy continuity", "abstract": "Version one."},
    )
    production_id = persist_normalized_record(session, first_raw.id)
    production = session.get(Production, production_id)
    assert production is not None
    production.canonical_key = f"source:{source.code}:oai:legacy:one"
    source.code = "renamed-source"
    second_raw = _raw(
        session,
        source,
        "oai:legacy:one",
        {"title": "Legacy continuity", "abstract": "Version two."},
    )

    recovered_id = persist_normalized_record(session, second_raw.id)

    assert recovered_id == production_id
    assert production.canonical_key == "source:legacy-source:oai:legacy:one"
    versions = session.scalars(
        select(ProductionVersion)
        .where(ProductionVersion.production_id == production_id)
        .order_by(ProductionVersion.version)
    ).all()
    assert [version.abstract for version in versions] == ["Version one.", "Version two."]
```

```python
def test_ambiguous_raw_provenance_is_rejected_instead_of_guessed(
    session: Session,
) -> None:
    source = _source(session, "ambiguous-legacy-source")
    first_raw = _raw(
        session,
        source,
        "oai:legacy:ambiguous",
        {"title": "First legacy branch"},
    )
    second_raw = _raw(
        session,
        source,
        "oai:legacy:ambiguous",
        {"title": "Second legacy branch"},
    )
    first = Production(canonical_key="legacy:first", current_version_number=1)
    second = Production(canonical_key="legacy:second", current_version_number=1)
    session.add_all([first, second])
    session.flush()
    session.add_all(
        [
            ProductionVersion(
                production_id=first.id,
                raw_record_id=first_raw.id,
                version=1,
                title="First legacy branch",
            ),
            ProductionVersion(
                production_id=second.id,
                raw_record_id=second_raw.id,
                version=1,
                title="Second legacy branch",
            ),
        ]
    )
    session.flush()
    incoming = _raw(
        session,
        source,
        "oai:legacy:ambiguous",
        {"title": "Ambiguous source history"},
    )

    with pytest.raises(ValueError, match="ambiguous source provenance"):
        persist_normalized_record(session, incoming.id)

    assert session.get(Production, first.id) is not None
    assert session.get(Production, second.id) is not None
```

Use the existing `_raw` helper in the test file; the explicit setup above deliberately represents historical split data that the current normalizer would no longer create.

- [ ] **Step 2: Run both tests and verify RED**

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m pytest tests/normalization/test_final_review_normalization.py -k "legacy_source_key or ambiguous_raw_provenance" -v
```

Expected: the continuity test creates a second production because UUID-scoped textual matching cannot find the legacy key; the ambiguity test does not raise the required error.

- [ ] **Step 3: Add provenance-first matching**

Add this helper in `normalization/service.py`:

```python
def _production_for_source_provenance(
    session: Session, raw: RawRecord
) -> Production | None:
    production_ids = tuple(
        dict.fromkeys(
            session.scalars(
                select(Production.id)
                .join(
                    ProductionVersion,
                    ProductionVersion.production_id == Production.id,
                )
                .join(RawRecord, RawRecord.id == ProductionVersion.raw_record_id)
                .where(
                    RawRecord.source_id == raw.source_id,
                    RawRecord.source_identifier == raw.source_identifier,
                    RawRecord.id != raw.id,
                )
                .order_by(Production.id)
            ).all()
        )
    )
    if len(production_ids) > 1:
        raise ValueError("ambiguous source provenance: multiple productions share the identity")
    return session.get(Production, production_ids[0]) if production_ids else None
```

In `persist_normalized_record`, call this helper after validating the raw record and title but before `match_production`. When it returns a production, construct:

```python
MatchDecision(
    "exact",
    provenance_production.id,
    ("immutable source provenance",),
)
```

Use this decision before identifier/title matching while preserving the existing savepoint, version-allocation retry, canonical-key race recovery, author reconciliation, and auditing.

- [ ] **Step 4: Verify continuity and all deduplication rules**

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m pytest tests/normalization/test_final_review_normalization.py -v
python -m pytest tests/normalization/test_deduplication.py -v
```

Expected: all normalization tests PASS; the old key remains unchanged, the source rename advances the same production, and ambiguous provenance creates no new production/version.

- [ ] **Step 5: Commit Task 2**

```bash
git add apps/api/src/pci/normalization/service.py apps/api/tests/normalization/test_final_review_normalization.py
git commit -m "fix: preserve legacy source continuity"
```

---

### Task 3: Project storage availability from the current published version

**Files:**
- Modify: `apps/api/src/pci/productions/repository.py`
- Modify: `apps/api/src/pci/productions/service.py`
- Modify: `apps/api/tests/api/test_final_review_public_projection.py`

**Interfaces:**
- Consumes: the current `ProductionVersion.raw_record_id` joined as `PublicProductionRecord.raw_record`
- Produces: `PublicProductionRecord.source_tombstoned: bool`
- Removes: `PublicProductionRecord.live_raw_record`
- Preserves: tombstone invalidation without replacing the last valid bibliographic version

- [ ] **Step 1: Write failing rejected-observation projection tests**

Add a parameterized test that proves a newer rejected observation cannot hide or advertise full text for the current public version:

```python
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
```

- [ ] **Step 2: Run the projection tests and verify RED**

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m pytest tests/api/test_final_review_public_projection.py -k "rejected_observation_cannot_change" -v
```

Expected: both cases expose the storage state of the newest rejected raw observation instead of the current published version.

- [ ] **Step 3: Separate current-version storage from tombstone invalidation**

Change the repository record to:

```python
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
```

Replace `_live_raw_records` with `_source_tombstone_states`. For each current-version raw record, find the newest tombstone sharing `source_id` and `source_identifier`. Return `True` only when its `(collected_at, str(id))` ordering key is later than the current-version raw record; otherwise return `False`. A `None` current raw returns `False`.

Hydrate `source_tombstoned` from that map. Do not use a newer non-tombstone observation for storage or public metadata.

- [ ] **Step 4: Use the current version raw object in the service**

Update `_summary`:

```python
access_available = version.source_url is not None and not record.source_tombstoned
```

Update `_live_full_text_available`:

```python
def _live_full_text_available(record: repository.PublicProductionRecord) -> bool:
    raw = record.raw_record
    return bool(
        raw is not None
        and not raw.is_tombstone
        and not record.source_tombstoned
        and raw.stored_object is not None
        and raw.stored_object.status == "stored"
    )
```

- [ ] **Step 5: Verify projection, tombstones, and metadata visibility**

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m pytest tests/api/test_final_review_public_projection.py -v
python -m pytest tests/api/test_metadata_visibility.py tests/api/test_public_productions.py -v
```

Expected: all API tests PASS; rejected observations do not affect full text, and the existing tombstone test still returns unavailable access and `full_text_available: false`.

- [ ] **Step 6: Run the complete hardening verification gate**

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m pytest -q
ruff check src tests alembic
mypy src
cd ../..
make runtime-smoke
cd apps/api
DATABASE_URL=postgresql+psycopg://pci:pci@postgres:5432/pci alembic upgrade head --sql > /tmp/pci-continuity-upgrade.sql
DATABASE_URL=postgresql+psycopg://pci:pci@postgres:5432/pci alembic downgrade head:base --sql > /tmp/pci-continuity-downgrade.sql
cd ../..
git diff --check
git status --short
```

Expected: all tests, Ruff, mypy, runtime import, offline upgrade/downgrade DDL, and diff checks PASS; only the intentional plan/spec changes may precede the task commits; Docker-dependent integration remains explicitly unverified.

- [ ] **Step 7: Commit Task 3**

```bash
git add apps/api/src/pci/productions/repository.py apps/api/src/pci/productions/service.py apps/api/tests/api/test_final_review_public_projection.py
git commit -m "fix: bind public storage to current version"
```

## Completion Gate

- The same observation can be harvested, left unnormalized, and recovered by the next pipeline run without duplicate raw records or versions.
- Legacy code-scoped canonical productions receive new versions through immutable raw provenance after a source-code rename.
- Multiple productions sharing one legacy provenance identity cause a deterministic rejection rather than an automatic merge.
- Newer rejected observations cannot hide or advertise full text for older qualified metadata.
- A later tombstone still invalidates source access and full-text availability without replacing bibliographic metadata.
- The full suite, Ruff, mypy, runtime-only worker import, offline PostgreSQL upgrade/downgrade DDL, and `git diff --check` pass.
- Live Docker/PostgreSQL/Redis/MinIO behavior remains an explicit deployment verification gate.
