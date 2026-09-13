# Final Ingestion Concurrency and Bounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two remaining Important ingestion findings by protecting active storage ownership with a reclaimable lease and bounding immutable-provenance lookup to two distinct productions.

**Architecture:** Object-storage ownership remains database-mediated: a token plus a 15-minute timestamp forms a compare-and-set lease, and only absent or expired ownership may be replaced. Provenance ambiguity remains fail-closed, but its database query performs `DISTINCT` and `LIMIT 2` so work is independent of version-history length.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, pytest, SQLite test concurrency, PostgreSQL 17 production target.

**Spec:** `docs/superpowers/specs/2026-09-13-final-ingestion-concurrency-bounds-design.md`

## Global Constraints

- Keep the scope limited to the two residual Important findings.
- Use strict TDD: capture RED before implementation and GREEN afterward.
- The storage ownership lease is exactly 15 minutes.
- A non-expired `pending` owner cannot be replaced.
- A `pending` row with no lease timestamp is reclaimable for migration compatibility.
- Finalization clears both `attempt_token` and `attempt_started_at` in the same compare-and-set update.
- The provenance query must apply SQL `DISTINCT` and `LIMIT 2` before materialization.
- Do not weaken ambiguous-provenance rejection or append-only history.

---

### Task 1: Protect active object-storage attempts with a lease

**Files:**
- Create: `apps/api/alembic/versions/0009_storage_attempt_lease.py`
- Modify: `apps/api/src/pci/models/provenance.py`
- Modify: `apps/api/src/pci/ingestion/harvest.py`
- Test: `apps/api/tests/ingestion/test_final_review_ingestion.py`
- Test: `apps/api/tests/migrations/test_migrations.py`

**Interfaces:**
- Consumes: `RawRecordObject.attempt_token`, `_claim_storage_attempt(...) -> str | None`, and `_finalize_storage_attempt(...) -> bool`.
- Produces: nullable `RawRecordObject.attempt_started_at: datetime | None` and a 15-minute storage ownership lease enforced by atomic claim predicates.

- [ ] **Step 1: Write deterministic failing concurrency and recovery tests**

Add a test in which the first worker owns the pending row and blocks inside a successful object-store write. Start a later worker with a failing object store while that lease is active; assert the later worker does not upload or finalize, release the first worker, then assert `status == "stored"`, both ownership fields are `None`, `error_summary is None`, and no `raw_record_object.failed` audit exists. Add a direct claim test that sets `attempt_started_at` older than 15 minutes (and separately `None`) and asserts the row can be reclaimed with a new token.

- [ ] **Step 2: Run the focused tests and record RED**

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m pytest -q tests/ingestion/test_final_review_ingestion.py -k 'active_pending or expired_storage_lease'
```

Expected: FAIL because an active token is stolen and `attempt_started_at` does not exist.

- [ ] **Step 3: Add the lease column and migration**

Add `attempt_started_at` to `RawRecordObject` with `DateTime(timezone=True)` and create revision `0009_storage_attempt_lease` over `0008_bounded_catalog_matching`. Upgrade adds the nullable column; downgrade drops it. Extend migration tests to assert the column exists after upgrade and is absent after downgrade.

- [ ] **Step 4: Enforce active, expired, and legacy claim states atomically**

Define `STORAGE_ATTEMPT_LEASE = timedelta(minutes=15)`. Initial association creation stores one `now = utc_now()` with the new token. `_claim_storage_attempt` returns `None` for `stored` and for `pending` rows whose token and timestamp represent an unexpired lease. Its conditional `UPDATE` may claim `failed`, tokenless pending, timestamp-less legacy pending, or pending rows with `attempt_started_at <= now - STORAGE_ATTEMPT_LEASE`; it writes a new token, `attempt_started_at=now`, `status="pending"`, and clears the earlier error. Include prior token/timestamp predicates so concurrent reclaimers still converge on one owner.

In `_finalize_storage_attempt`, preserve the existing token/status compare-and-set and set both `attempt_token=None` and `attempt_started_at=None`. Include `attempt_started_at` in `_storage_snapshot` and transition audit snapshots.

- [ ] **Step 5: Run focused and neighboring tests and record GREEN**

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m pytest -q tests/ingestion/test_final_review_ingestion.py tests/ingestion/test_harvest_idempotency.py tests/migrations/test_migrations.py
ruff check src/pci/ingestion/harvest.py src/pci/models/provenance.py tests/ingestion/test_final_review_ingestion.py alembic/versions/0009_storage_attempt_lease.py
```

Expected: all tests and lint checks pass.

- [ ] **Step 6: Commit the storage lease fix**

```bash
git add apps/api/alembic/versions/0009_storage_attempt_lease.py apps/api/src/pci/models/provenance.py apps/api/src/pci/ingestion/harvest.py apps/api/tests/ingestion/test_final_review_ingestion.py apps/api/tests/migrations/test_migrations.py
git commit -m "fix: lease object storage attempts"
```

---

### Task 2: Bound source-provenance ambiguity lookup

**Files:**
- Modify: `apps/api/src/pci/normalization/service.py`
- Test: `apps/api/tests/normalization/test_final_review_normalization.py`

**Interfaces:**
- Consumes: `_production_for_source_provenance(session: Session, raw: RawRecord) -> Production | None`.
- Produces: the same return/error contract with a SQL query capped at two distinct production IDs.

- [ ] **Step 1: Write a failing SQL-boundary regression**

Create several historical `ProductionVersion` rows for one source identity, attach a SQLAlchemy `before_cursor_execute` listener during `_production_for_source_provenance`, and capture the provenance statement. Assert the emitted SELECT contains `DISTINCT` and a limit value of `2`; retain behavioral assertions for zero, unique, and ambiguous identities.

- [ ] **Step 2: Run the focused test and record RED**

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m pytest -q tests/normalization/test_final_review_normalization.py -k 'provenance_lookup_is_bounded'
```

Expected: FAIL because the current statement has neither SQL `DISTINCT` nor `LIMIT 2`.

- [ ] **Step 3: Push deduplication and the bound into SQL**

Replace Python `dict.fromkeys(...)` with:

```python
production_ids = tuple(
    session.scalars(
        select(Production.id)
        .distinct()
        .join(ProductionVersion, ProductionVersion.production_id == Production.id)
        .join(RawRecord, RawRecord.id == ProductionVersion.raw_record_id)
        .where(
            RawRecord.source_id == raw.source_id,
            RawRecord.source_identifier == raw.source_identifier,
            RawRecord.id != raw.id,
        )
        .order_by(Production.id)
        .limit(2)
    ).all()
)
```

Keep the existing `len(production_ids) > 1` ambiguity error and unique/empty return behavior unchanged.

- [ ] **Step 4: Run focused and neighboring tests and record GREEN**

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m pytest -q tests/normalization/test_final_review_normalization.py tests/normalization/test_deduplication.py
ruff check src/pci/normalization/service.py tests/normalization/test_final_review_normalization.py
```

Expected: all tests and lint checks pass.

- [ ] **Step 5: Commit the bounded provenance fix**

```bash
git add apps/api/src/pci/normalization/service.py apps/api/tests/normalization/test_final_review_normalization.py
git commit -m "fix: bound source provenance lookup"
```

---

### Final verification

- [ ] Run the complete API pytest suite.
- [ ] Run Ruff check, mypy, runtime smoke, Alembic offline upgrade/downgrade, and `git diff --check`.
- [ ] Obtain fresh task reviews and one whole-change final review with no open Critical or Important findings.
- [ ] Record exact commands, counts, commits, and rulings in the SDD ledger.
