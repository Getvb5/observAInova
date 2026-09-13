# Final Ingestion Concurrency and Bounds Design

## Context

The ingestion-continuity hardening branch passed its implementation gate, but the scoped re-review of its only final fix wave found two remaining Important defects. This micro-design closes only those defects and does not add product functionality.

## Problem 1: active storage ownership can be stolen

`_claim_storage_attempt` currently replaces any non-stored association's `attempt_token`, including a `pending` association whose upload is still active. In the inverse race—older successful upload blocked, newer failing upload starts—the newer worker can steal ownership, finalize `failed`, and make the successful worker's compare-and-set ineffective.

### Required behavior

- A `pending` association with a non-expired ownership lease cannot be claimed by another worker.
- An abandoned `pending` attempt remains recoverable after a fixed 15-minute lease.
- Initial creation and every successful claim set both `attempt_token` and `attempt_started_at`.
- Successful or failed finalization clears both ownership fields atomically.
- The final status of a successful active owner cannot be downgraded by a competing failure.
- PostgreSQL and SQLite behavior must remain supported.

### Data change

Add nullable `raw_record_objects.attempt_started_at` as a timezone-aware timestamp. Existing rows remain nullable; a `pending` row without a timestamp is reclaimable as legacy/unowned state. Downgrade drops only this column.

## Problem 2: provenance lookup is unbounded

`_production_for_source_provenance` loads every matching historical version and deduplicates in Python. Work therefore grows with the total number of versions for one immutable source identity even though the decision needs only zero, one, or more-than-one production IDs.

### Required behavior

- The database query selects distinct `Production.id` values.
- It requests at most two IDs.
- Zero IDs returns `None`, one returns that production, and two raises the existing ambiguity error.
- No full historical result set is materialized in Python.

## Verification

- A deterministic two-worker regression proves an active successful upload cannot have its token stolen by a later failing worker.
- A lease regression proves an expired or legacy pending attempt can be reclaimed.
- A SQL-shape regression proves the provenance query contains both `DISTINCT` and `LIMIT 2`, while existing unique and ambiguous behavior tests remain green.
- The complete API test, lint, type, migration, runtime-smoke, and diff gates must pass before integration is offered.

## Non-goals

- Distributed lock services.
- Background lease-renewal heartbeats.
- Changes to public API behavior.
- New matching heuristics or schema refactors beyond the lease timestamp.
