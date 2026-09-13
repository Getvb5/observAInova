# Scientific Evaluation and Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the platform scientifically evaluable and operationally trustworthy through stratified sampling, reproducible benchmarks, usability measurement, observability, resilience, security, and release gates.

**Architecture:** Derive research datasets and operational metrics from immutable canonical records without changing production data. Run evaluation jobs with versioned inputs and outputs, expose aggregate internal dashboards, keep participant data restricted, and enforce automated release checks.

**Tech Stack:** Python 3.12, FastAPI, PostgreSQL 17, SQLAlchemy 2, pandas, scikit-learn, scipy, pytest, Locust, Playwright, axe-core, OpenTelemetry, Prometheus-compatible metrics, structured JSON logging.

**Spec:** `docs/superpowers/specs/2026-09-08-pernambuco-ciencia-inovacao-design.md`

## Global Constraints

- Plans 1–3 must be complete before the final release gate.
- Evaluation artifacts must record corpus, taxonomy, prompt, model, search configuration, timestamp, and code commit versions.
- Sampling must represent areas, institutions, production types, periods, territorial universes, and text availability.
- Evaluation code must never mutate canonical production or validation records.
- Raw participant data and internal validation history are restricted; public reporting uses aggregates.
- Required thresholds are 100% validated public semantics, 100% citation traceability, 100% provenance, at least 80% task success, and mean SUS at least 68.
- Semantic retrieval must outperform the lexical baseline on the frozen evaluation set before release.

---

## Repository Map Additions

```text
apps/api/src/pci/evaluation/
apps/api/src/pci/observability/
apps/api/src/pci/quality/
apps/api/tests/evaluation/
apps/api/tests/resilience/
apps/api/tests/security/
research/schemas/
research/instruments/
research/scripts/
research/reports/.gitkeep
loadtests/locustfile.py
docs/operations/runbook.md
docs/operations/data-governance.md
```

### Task 1: Implement data-quality metrics and stratified sampling

**Files:**
- Create: `apps/api/src/pci/quality/metrics.py`
- Create: `apps/api/src/pci/evaluation/sampling.py`
- Create: `apps/api/src/pci/evaluation/schemas.py`
- Create: `apps/api/src/pci/evaluation/repository.py`
- Create: `apps/api/alembic/versions/0009_evaluation_runs.py`
- Create: `apps/api/tests/evaluation/test_quality_metrics.py`
- Create: `apps/api/tests/evaluation/test_stratified_sample.py`
- Create: `research/schemas/sample-manifest.schema.json`

**Interfaces:**
- Produces: `calculate_quality_snapshot(session: Session, corpus_version: str) -> QualitySnapshot`
- Produces: `build_stratified_sample(session: Session, config: SampleConfig, seed: int) -> SampleManifest`
- Produces: `Stratum(area_code, institution_type, production_type, period_band, territory_relation, text_availability)`
- Produces: `SampleManifest` with selected IDs, stratum counts, weights, seed, corpus version, and checksum

- [ ] **Step 1: Write failing quality and sample tests**

```python
def test_quality_snapshot_reports_provenance_and_missingness(session, corpus) -> None:
    snapshot = calculate_quality_snapshot(session, corpus.version)
    assert snapshot.total_records == 12
    assert snapshot.provenance_rate == 1.0
    assert snapshot.field_completeness["abstract"] == pytest.approx(9 / 12)
    assert snapshot.duplicate_candidate_rate == pytest.approx(2 / 12)


def test_sample_is_representative_and_reproducible(session, corpus) -> None:
    config = SampleConfig(target_size=8, minimum_per_stratum=1)
    first = build_stratified_sample(session, config, seed=20260908)
    second = build_stratified_sample(session, config, seed=20260908)
    assert first.checksum == second.checksum
    assert first.selected_production_ids == second.selected_production_ids
    assert all(count >= 1 for count in first.selected_counts.values())
```

- [ ] **Step 2: Run tests and verify the initial failure**

Run: `cd apps/api && python -m pytest tests/evaluation/test_quality_metrics.py tests/evaluation/test_stratified_sample.py -v`

Expected: FAIL because quality and sampling modules do not exist.

- [ ] **Step 3: Implement snapshots and deterministic proportional allocation**

Calculate completeness by field, provenance rate, duplicate-candidate rate, source freshness, territorial coverage, validation coverage, and distributions by stratum. Define period bands as `before_2000`, `2000_2009`, `2010_2019`, `2020_present`, and `unknown`.

Allocate proportionally, enforce `minimum_per_stratum` while capacity permits, select with a seeded generator, and store inclusion probabilities and weights. Freeze every manifest; changed corpus or configuration creates a new run.

- [ ] **Step 4: Apply the migration and verify deterministic results**

Run:

```bash
cd apps/api
alembic upgrade head
python -m pytest tests/evaluation/test_quality_metrics.py tests/evaluation/test_stratified_sample.py -v
ruff check src tests
mypy src
```

Expected: all checks pass; identical inputs and seed reproduce the checksum; unavailable strata are explicitly reported.

- [ ] **Step 5: Commit quality and sampling**

```bash
git add apps/api research/schemas
git commit -m "feat: add reproducible quality and sampling metrics"
```

### Task 2: Build extraction and retrieval evaluation harnesses

**Files:**
- Create: `research/schemas/gold-annotations.schema.json`
- Create: `research/schemas/relevance-judgments.schema.json`
- Create: `research/scripts/evaluate_extraction.py`
- Create: `research/scripts/evaluate_retrieval.py`
- Create: `fixtures/evaluation/gold.json`
- Create: `fixtures/evaluation/predicted.json`
- Create: `fixtures/evaluation/judgments.json`
- Create: `fixtures/evaluation/runs.json`
- Create: `apps/api/src/pci/evaluation/extraction_metrics.py`
- Create: `apps/api/src/pci/evaluation/retrieval_metrics.py`
- Create: `apps/api/tests/evaluation/test_extraction_metrics.py`
- Create: `apps/api/tests/evaluation/test_retrieval_metrics.py`

**Interfaces:**
- Produces: `evaluate_extraction(gold: AnnotationSet, predicted: AnnotationSet) -> ExtractionReport`
- Produces: `evaluate_retrieval(run: RetrievalRun, judgments: RelevanceJudgments, k: int = 10) -> RetrievalReport`
- Produces per-kind and macro precision, recall, F1, agreement, Precision@10, nDCG@10, coverage, and institutional diversity

- [ ] **Step 1: Write failing tests from hand-calculated examples**

```python
def test_extraction_metrics_match_hand_calculation() -> None:
    gold = annotations({"problem": {"p1", "p2"}, "solution": {"s1"}})
    predicted = annotations({"problem": {"p1", "p3"}, "solution": {"s1"}})
    report = evaluate_extraction(gold, predicted)
    assert report.by_kind["problem"].precision == pytest.approx(0.5)
    assert report.by_kind["problem"].recall == pytest.approx(0.5)
    assert report.by_kind["solution"].f1 == pytest.approx(1.0)


def test_retrieval_rewards_relevant_results_near_the_top() -> None:
    judgments = relevance({"q1": {"d1": 3, "d2": 1, "d3": 0}})
    lexical = retrieval_run({"q1": ["d3", "d2", "d1"]})
    semantic = retrieval_run({"q1": ["d1", "d2", "d3"]})
    assert evaluate_retrieval(semantic, judgments).ndcg_at_10 > evaluate_retrieval(lexical, judgments).ndcg_at_10
```

- [ ] **Step 2: Run metric tests and verify the initial failure**

Run: `cd apps/api && python -m pytest tests/evaluation/test_extraction_metrics.py tests/evaluation/test_retrieval_metrics.py -v`

Expected: FAIL because metric functions do not exist.

- [ ] **Step 3: Implement reproducible metrics and report commands**

Match extracted entities by production, semantic kind, concept code, and normalized span overlap. Report exact and relaxed span scores, per-kind, micro, and macro precision, recall, and F1. For double-coded records, report agreement with sample size.

Accept frozen queries, ranked IDs, and graded relevance judgments from 0 to 3. Report Precision@10, nDCG@10, recall over judged relevant items, coverage, unique institutions, unique areas, and paired per-query differences between lexical and hybrid runs. Save JSON and CSV with a complete version manifest.

- [ ] **Step 4: Run unit tests and fixture benchmarks**

Run:

```bash
cd apps/api
python -m pytest tests/evaluation/test_extraction_metrics.py tests/evaluation/test_retrieval_metrics.py -v
cd ../..
python research/scripts/evaluate_extraction.py --gold fixtures/evaluation/gold.json --predicted fixtures/evaluation/predicted.json --out research/reports/extraction-fixture.json
python research/scripts/evaluate_retrieval.py --judgments fixtures/evaluation/judgments.json --runs fixtures/evaluation/runs.json --out research/reports/retrieval-fixture.json
```

Expected: tests pass; both scripts exit 0; reports contain inputs, versions, metrics, timestamp, and checksum.

- [ ] **Step 5: Commit evaluation harnesses**

```bash
git add apps/api research fixtures/evaluation
git commit -m "feat: add reproducible extraction and retrieval evaluation"
```

### Task 3: Instrument usability and usefulness evaluation

**Files:**
- Create: `research/instruments/task-scenarios.md`
- Create: `research/instruments/post-task-questionnaire.md`
- Create: `research/instruments/sus-questionnaire.md`
- Create: `research/schemas/usability-session.schema.json`
- Create: `apps/api/src/pci/evaluation/usability.py`
- Create: `apps/api/src/pci/evaluation/usability_router.py`
- Create: `apps/api/tests/evaluation/test_usability_metrics.py`
- Create: `apps/web/src/lib/evaluation-events.ts`
- Create: `apps/web/tests/e2e/evaluation-events.spec.ts`

**Interfaces:**
- Produces anonymous events `task_started`, `search_submitted`, `result_opened`, `source_opened`, `comparison_completed`, `task_completed`, and `task_abandoned`
- Produces: `calculate_sus(responses: tuple[int, ...]) -> float`
- Produces: `summarize_usability(sessions: Sequence[UsabilitySession]) -> UsabilityReport`
- Produces: restricted `POST /api/v1/evaluation/sessions`

- [ ] **Step 1: Write failing SUS and task-success tests**

```python
def test_sus_uses_the_standard_alternating_formula() -> None:
    responses = (4, 2, 4, 2, 4, 2, 4, 2, 4, 2)
    assert calculate_sus(responses) == 75.0


def test_task_success_excludes_invalid_sessions() -> None:
    report = summarize_usability([
        session(valid=True, completed=True, seconds=90),
        session(valid=True, completed=False, seconds=180),
        session(valid=False, completed=True, seconds=20),
    ])
    assert report.task_success_rate == 0.5
    assert report.valid_session_count == 2
```

- [ ] **Step 2: Run usability tests and verify the initial failure**

Run: `cd apps/api && python -m pytest tests/evaluation/test_usability_metrics.py -v`

Expected: FAIL because usability metrics and event ingestion do not exist.

- [ ] **Step 3: Implement instruments, consent-aware events, and summaries**

Create four task scenarios: find a solution, compare two solutions, locate a competence, and verify an evidence source. Capture success, difficulty, confidence, usefulness, and comments. Store only a random study session ID, participant group, timestamps, task events, responses, and consent version; exclude IP addresses from the research dataset.

Validate exactly ten SUS answers from 1 to 5. Summaries report task success, median time, errors, abandonments, mean SUS, usefulness, and participant-group aggregates.

- [ ] **Step 4: Verify metrics and the browser event sequence**

Run:

```bash
cd apps/api && python -m pytest tests/evaluation/test_usability_metrics.py -v
cd ../web && pnpm playwright test tests/e2e/evaluation-events.spec.ts
```

Expected: tests pass; events are emitted only after evaluation consent; the endpoint rejects a missing consent version and extraneous personal fields.

- [ ] **Step 5: Commit usability evaluation**

```bash
git add research/instruments research/schemas apps/api apps/web
git commit -m "feat: instrument usability and usefulness evaluation"
```

### Task 4: Add observability, resilience, security, and performance checks

**Files:**
- Create: `apps/api/src/pci/observability/logging.py`
- Create: `apps/api/src/pci/observability/metrics.py`
- Create: `apps/api/src/pci/observability/tracing.py`
- Create: `apps/api/tests/resilience/test_source_outage.py`
- Create: `apps/api/tests/resilience/test_index_failure.py`
- Create: `apps/api/tests/security/test_publication_bypass.py`
- Create: `apps/api/tests/security/test_role_matrix.py`
- Create: `loadtests/locustfile.py`
- Create: `docs/operations/runbook.md`

**Interfaces:**
- Produces metrics `harvest_runs_total`, `harvest_failures_total`, `validation_queue_depth`, `validation_duration_seconds`, `semantic_publication_blocked_total`, `search_duration_seconds`, and `answer_grounding_failures_total`
- Produces correlation fields `request_id`, `harvest_run_id`, `production_id`, `validation_item_id`, and `search_session_id`
- Consumes all prior services without changing their domain results

- [ ] **Step 1: Write failing resilience and security tests**

```python
import asyncio


def test_source_outage_preserves_last_public_version(
    client, session, source, failing_connector, public_production
) -> None:
    run = asyncio.run(harvest_source(session, failing_connector, source.id))
    assert run.status == "failed"
    response = client.get(f"/api/v1/productions/{public_production.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(public_production.id)


def test_direct_visibility_update_cannot_bypass_validation(session, private_solution) -> None:
    with pytest.raises(IntegrityError):
        session.execute(update(Solution).where(Solution.id == private_solution.id).values(visibility="public"))
        session.commit()
```

- [ ] **Step 2: Run resilience and security tests and verify the initial failure**

Run: `cd apps/api && python -m pytest tests/resilience tests/security -v`

Expected: FAIL because observability hooks and database enforcement are incomplete.

- [ ] **Step 3: Implement fail-safe behavior, metrics, and exact runbook procedures**

Emit structured JSON without full source text, AI prompts, tokens, participant responses, or email addresses. Trace ingestion, extraction, validation, indexing, search, and answer calls. Add database enforcement that rejects public semantic visibility without an approved decision and source span.

Document commands for checking health, pausing a connector, retrying a harvest, rebuilding the index, reopening validation after taxonomy changes, rotating OIDC configuration, restoring a backup, and verifying the last public version.

- [ ] **Step 4: Run resilience checks and a baseline load profile**

Run:

```bash
cd apps/api
python -m pytest tests/resilience tests/security -v
ruff check src tests
mypy src
cd ../..
locust -f loadtests/locustfile.py --headless -u 50 -r 5 -t 2m --host http://localhost:8000
```

Expected: tests pass; 50 concurrent search users complete the profile with zero authorization or publication-gate errors; measured latency percentiles are recorded without being presented as production capacity.

- [ ] **Step 5: Commit operational safeguards**

```bash
git add apps/api loadtests docs/operations
git commit -m "feat: add observability and operational safeguards"
```

### Task 5: Implement the reproducible release gate

**Files:**
- Create: `research/scripts/build_release_report.py`
- Create: `research/schemas/release-report.schema.json`
- Create: `apps/api/src/pci/evaluation/release_gate.py`
- Create: `docs/operations/data-governance.md`
- Modify: `Makefile`
- Create: `.github/workflows/verify.yml`
- Create: `apps/api/tests/evaluation/test_release_gate.py`

**Interfaces:**
- Produces: `ReleaseGate.evaluate(inputs: ReleaseInputs) -> ReleaseDecision`
- Produces: `ReleaseDecision(allowed: bool, failures: tuple[str, ...], metrics: dict[str, float], manifest: VersionManifest)`
- Produces commands: `make verify`, `make evaluate`, and `make release-report`
- Consumes quality, extraction, retrieval, usability, security, and traceability reports

- [ ] **Step 1: Write failing release-decision tests**

```python
def test_release_passes_only_when_all_thresholds_are_met() -> None:
    decision = ReleaseGate.evaluate(release_inputs(
        validated_public_semantics_rate=1.0,
        citation_traceability_rate=1.0,
        provenance_rate=1.0,
        hybrid_ndcg_at_10=0.74,
        lexical_ndcg_at_10=0.61,
        task_success_rate=0.82,
        mean_sus=72.0,
        authorization_failures=0,
        publication_gate_failures=0,
    ))
    assert decision.allowed is True


def test_release_fails_when_a_public_item_lacks_validation() -> None:
    decision = ReleaseGate.evaluate(release_inputs(validated_public_semantics_rate=0.999))
    assert decision.allowed is False
    assert "validated_public_semantics_rate must equal 1.0" in decision.failures
```

- [ ] **Step 2: Run release tests and verify the initial failure**

Run: `cd apps/api && python -m pytest tests/evaluation/test_release_gate.py -v`

Expected: FAIL because the release gate and report builder do not exist.

- [ ] **Step 3: Implement exact gates, CI, and governance documentation**

The release decision requires:

```text
validated_public_semantics_rate == 1.0
citation_traceability_rate == 1.0
provenance_rate == 1.0
hybrid_ndcg_at_10 > lexical_ndcg_at_10
task_success_rate >= 0.80
mean_sus >= 68.0
authorization_failures == 0
publication_gate_failures == 0
```

The report includes commit, corpus, taxonomy, prompt, model, and search-configuration versions; sample manifest; metric summaries; failures; and final decision. CI runs backend, frontend, browser, lint, type, migration, accessibility, and security checks. Participant-data evaluation runs only in the controlled research environment and contributes an aggregate report.

Document retention, lawful access, roles, backups, versioning, participant-data separation, and publication rules in `data-governance.md`.

- [ ] **Step 4: Run the full verification and build the release report**

Run:

```bash
make verify
make evaluate
make release-report
```

Expected: automated checks exit 0; `research/reports/release-report.json` validates against its schema and contains `allowed: true`. A failed threshold makes the command exit nonzero and list every failed rule.

- [ ] **Step 5: Commit the release gate**

```bash
git add .github Makefile apps research docs/operations
git commit -m "feat: enforce scientific and technical release gates"
```

## Requirements Traceability

| Spec requirements | Implemented by |
|---|---|
| RF-01–RF-05 | Plan 1, Tasks 2–5 |
| RF-06–RF-10 | Plan 2, Tasks 2–5 |
| RF-11–RF-16 | Plan 3, Tasks 1–5 |
| RF-17 | Plan 2, Task 1 |
| RF-18 | Plan 4, Tasks 1 and 4 |
| RF-19 | Plan 3, Task 5 and Plan 4, Task 3 |
| RF-20 | Plan 2, Task 5 |
| RNF-01 | Plan 1, Tasks 2–4 |
| RNF-02–RNF-03 | Plan 2, Tasks 3–5 |
| RNF-04–RNF-05 | Plan 1, Tasks 2–5 and Plan 3, Task 1 |
| RNF-06 | Plan 1, Task 3 and Plan 4, Task 4 |
| RNF-07 | Plan 2, Task 3 and Plan 4, Task 4 |
| RNF-08 | Plan 3, Tasks 3–4 |
| RNF-09 | Plan 2, Tasks 1 and 5; Plan 3, Task 2 |
| RNF-10 | Plan 1, Task 3 |
| RNF-11 | Plan 4, Tasks 1–5 |
| RNF-12 | File maps and interfaces in Plans 1–4 |

## Plan 4 Completion Gate

- Sampling is reproducible and representation is auditable.
- Extraction and retrieval evaluation runs from frozen, versioned inputs.
- Usability and usefulness measures follow the approved design.
- Operational failures preserve the last valid public state.
- Authorization and publication gates fail closed.
- One command produces a machine-readable decision against every approved criterion.
