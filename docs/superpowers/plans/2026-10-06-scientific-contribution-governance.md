# Scientific Contribution Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the private AI-extraction, central-team curation, four-eyes publication, and public validated-contribution vertical slice for theses and dissertations in ObservAInova.

**Architecture:** Extend the existing FastAPI/PostgreSQL foundation with append-only document, extraction, review, and publication records. OIDC protects internal routes; provider-neutral extraction creates only private candidates; a curator validates every field; a different supervisor authorizes an immutable public projection delivered through a transactional outbox. The current problem-first homepage remains unchanged, and the future matching/pathway subsystem will consume only the safe public projection.

**Tech Stack:** Python 3.12, FastAPI 0.115, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 17 with pgvector, Dramatiq, Redis, MinIO/S3, PyJWT 2.x with cryptography, pypdf 6.x, httpx, pytest, Next.js 15, React 19, TypeScript, Vitest, Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-23-scientific-contribution-governance-design.md`

## Global Constraints

- The current Alembic head is `0010_public_problem_formulation`; this plan owns revisions `0011` through `0015` in a single linear chain.
- Preserve the existing problem-first homepage and all ingestion, normalization, qualification, production, and problem API contracts.
- The initial scientific corpus is theses and dissertations from public institutions headquartered in Pernambuco, analytically covering 2016–2025 with 2026 as a separately tracked current layer.
- All knowledge areas remain eligible; missing program or area metadata is an explicit `not_informed` stratum, not a reason to discard a production.
- Full text is primary only when access and storage rights allow it; the abstract is a labeled fallback, and image-only PDFs enter `ocr_required` without automatic OCR in this phase.
- No provider response, candidate claim, confidence score, private span, rejected value, or review note may be serialized by a public endpoint.
- Every public scientific field has a human decision and recoverable provenance; `abstract_only` fields display the exact limitation.
- Curator and publishing supervisor must have different `(issuer, subject)` identities for the same contribution version.
- Published scientific values are immutable; correction creates a new version, and revocation removes the public projection without deleting history.
- AI and OIDC providers are configured behind interfaces; tests use deterministic providers and local signed tokens without network access.
- Local authentication is forbidden when `APP_ENV` is not `development` or `test`.
- Add `PyJWT[crypto]>=2.15,<3.0` and `pypdf>=6.18,<7.0`; preserve the existing dependency version floors and Python `>=3.12,<3.13`.
- Public and internal Pydantic schemas use `extra="forbid"`; free text has explicit length bounds; every list endpoint has bounded pagination and stable ordering.
- All user-facing copy is Brazilian Portuguese, all actions are keyboard operable, and focus moves to the result or error after asynchronous actions.
- Each task follows TDD, runs the focused suite plus relevant regression checks, and ends in its own commit.

## Review Focus

1. A restricted source, an off-domain redirect, or a response that is not actually a PDF must never be stored or parsed; Task 3 pins rights, host, redirect, size, and media-type behavior.
2. Unicode text, page boundaries, repeated quotations, and a changed source version must not corrupt grounding offsets; Tasks 2–4 pin normalized offsets, hashes, and exact source-version identity.
3. Malformed provider JSON, unsupported fields, invalid confidence, mismatched quotations, timeout, and explicit reruns must fail privately without overwriting earlier runs; Task 4 pins each case.
4. Expired/wrong-issuer/wrong-audience JWTs, role escalation, local tokens in production, and curator self-publication must be rejected without partial state changes; Tasks 1, 6, and 8 pin these boundaries.
5. Duplicate/out-of-order outbox delivery, worker failure after projection, supersession, and revocation must converge on exactly one active public version with no private fields; Task 8 pins idempotency and visibility.

---

## Repository Map for This Subproject

```text
apps/api/
  alembic/versions/
    0011_document_intelligence.py
    0012_candidate_extractions.py
    0013_review_sampling.py
    0014_scientific_contributions.py
    0015_publication_projection.py
  src/pci/
    auth/
      contracts.py
      dependencies.py
      oidc.py
    claims/
      contracts.py
      enums.py
      providers.py
      repository.py
      service.py
      tasks.py
    contributions/
      repository.py
      schemas.py
      service.py
    documents/
      contracts.py
      locators.py
      repository.py
      service.py
      tasks.py
      text.py
    evaluation/
      schemas.py
      service.py
    models/
      claims.py
      contributions.py
      documents.py
      publication.py
      review.py
    publication/
      repository.py
      service.py
      tasks.py
    review/
      repository.py
      sampling.py
      schemas.py
      service.py
    routers/
      internal_contributions.py
      public_contributions.py
  tests/
    auth/
    claims/
    contributions/
    documents/
    evaluation/
    publication/
    review/
    api/
    migrations/
apps/web/
  src/app/
    contribuicoes/[contributionId]/page.tsx
    equipe/page.tsx
  src/components/contributions/
  src/components/review/
  src/lib/contribution-api.ts
  src/lib/internal-api.ts
  src/lib/internal-auth.tsx
  e2e/contribution-governance.spec.ts
docs/development/scientific-contribution-flow.md
```

### Task 1: Protect internal APIs with provider-independent OIDC

**Files:**
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/uv.lock`
- Modify: `apps/api/src/pci/settings.py`
- Create: `apps/api/src/pci/auth/__init__.py`
- Create: `apps/api/src/pci/auth/contracts.py`
- Create: `apps/api/src/pci/auth/oidc.py`
- Create: `apps/api/src/pci/auth/dependencies.py`
- Modify: `apps/api/src/pci/main.py`
- Create: `apps/api/tests/auth/test_oidc.py`
- Create: `apps/api/tests/auth/test_internal_authorization.py`
- Modify: `apps/api/tests/api/conftest.py`

**Interfaces:**
- Produces enum `Role` with `CURATOR`, `SUPERVISOR`, and `ADMIN`.
- Produces `AuthPrincipal(issuer: str, subject: str, display_name: str | None, roles: frozenset[Role])` and property `actor_key: str` equal to `f"{issuer}|{subject}"`.
- Produces protocol `TokenVerifier.verify(token: str) -> AuthPrincipal`.
- Produces `OidcTokenVerifier.from_settings(settings: Settings) -> OidcTokenVerifier` and `LocalTokenVerifier(secret: str, issuer: str, audience: str)`.
- Produces `get_principal(request: Request, authorization: str) -> AuthPrincipal` and `require_roles(*roles: Role) -> Callable[..., AuthPrincipal]`.
- Later tasks consume `PrincipalDependency`, `CuratorDependency`, `SupervisorDependency`, and `AdminDependency` from `pci.auth.dependencies`.

- [ ] **Step 1: Write failing JWT and role tests**

```python
def test_oidc_rejects_wrong_issuer_audience_and_expired_tokens(verifier, token_factory) -> None:
    for token in (
        token_factory(issuer="https://wrong.example"),
        token_factory(audience="wrong-api"),
        token_factory(expires_in=-1),
    ):
        with pytest.raises(AuthenticationError):
            verifier.verify(token)


def test_local_auth_cannot_start_in_production() -> None:
    with pytest.raises(ValueError, match="local authentication"):
        Settings(app_env="production", auth_mode="local", local_auth_secret="secret")


def test_curator_route_rejects_supervisor_only_token(internal_client, supervisor_token) -> None:
    response = internal_client.get(
        "/api/v1/internal/auth-check/curator",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    assert response.status_code == 403
```

- [ ] **Step 2: Run the tests and confirm missing auth contracts**

Run: `cd apps/api && uv run python -m pytest tests/auth -v`

Expected: FAIL during collection because `pci.auth` does not exist.

- [ ] **Step 3: Add settings and JWT verification**

Add exact settings: `app_env`, `auth_mode`, `oidc_issuer`, `oidc_audience`, `oidc_jwks_url`, `oidc_algorithms`, `oidc_roles_claim`, `oidc_role_map`, `local_auth_secret`, and `local_auth_issuer`. `OidcTokenVerifier` must cache the JWKS client, allow-list configured algorithms, and require `exp`, `iss`, `sub`, and `aud`. Map only explicitly configured claim values to the closed `Role` enum.

- [ ] **Step 4: Add FastAPI dependencies and CORS support**

Resolve the verifier from `app.state.token_verifier` in tests or settings in production. Return 401 with `WWW-Authenticate: Bearer` for authentication failures and 403 for insufficient roles. Add `Authorization` to allowed CORS headers. Add test-only auth-check routes inside the fixture app, not production routes.

- [ ] **Step 5: Verify focused and regression checks**

Run:

```bash
cd apps/api
uv run python -m pytest tests/auth tests/api/test_problem_api.py tests/api/test_public_productions.py -v
uv run ruff check src tests
uv run mypy src
```

Expected: auth tests pass; the existing unauthenticated public APIs remain unchanged; Ruff and mypy pass.

- [ ] **Step 6: Commit internal authentication**

```bash
git add apps/api/pyproject.toml apps/api/uv.lock apps/api/src/pci/auth \
  apps/api/src/pci/settings.py apps/api/src/pci/main.py apps/api/tests/auth \
  apps/api/tests/api/conftest.py
git commit -m "feat: secure internal APIs with OIDC"
```

### Task 2: Model academic metadata and immutable document text

**Files:**
- Create: `apps/api/src/pci/models/documents.py`
- Modify: `apps/api/src/pci/models/production.py`
- Modify: `apps/api/src/pci/models/__init__.py`
- Modify: `apps/api/src/pci/normalization/contracts.py`
- Modify: `apps/api/src/pci/normalization/records.py`
- Modify: `apps/api/src/pci/normalization/service.py`
- Create: `apps/api/alembic/versions/0011_document_intelligence.py`
- Create: `apps/api/tests/documents/test_models.py`
- Modify: `apps/api/tests/normalization/test_normalize_record.py`
- Create: `apps/api/tests/migrations/test_document_intelligence_migration.py`

**Interfaces:**
- Extends `NormalizedRecord` and `ProductionVersion` with `academic_program: str | None` and `knowledge_areas: tuple[str, ...]`/`list[str] | None`.
- Produces `SourceDocumentStatus` with `PENDING`, `RETRIEVED`, `TEXT_EXTRACTED`, `OCR_REQUIRED`, `RESTRICTED`, `FAILED`, and `SUPERSEDED`.
- Produces `DocumentTextScope` with `FULL_TEXT` and `ABSTRACT_ONLY`, plus `TextExtractionMethod` with `PYPDF`, `METADATA_ABSTRACT`, `MANUAL`, and reserved `OCR`.
- Produces models `SourceDocument`, `DocumentTextVersion`, and `DocumentPage`.
- `SourceDocument` owns acquisition status, official URL, same-origin host, object key/checksum, media type, size, rights snapshot, error code, and supersession.
- `DocumentTextVersion` owns immutable normalized text, scope, method, checksum, version, and source-document identity.
- `DocumentPage` owns 1-based page number plus half-open global offsets `[start_offset, end_offset)` and page checksum.

- [ ] **Step 1: Write failing normalization and model tests**

```python
def test_academic_metadata_is_optional_and_preserved() -> None:
    record = normalize_record(harvested_record({
        "title": "Tese",
        "program": "Ciência da Informação",
        "knowledge_area": ["Ciências Sociais Aplicadas", "Ciência da Informação"],
    }))
    assert record.academic_program == "Ciência da Informação"
    assert record.knowledge_areas == (
        "Ciências Sociais Aplicadas",
        "Ciência da Informação",
    )


def test_document_text_and_pages_are_append_only(session, production_version) -> None:
    text = ready_text_version(production_version, "ação pública\nsegunda página")
    session.add(text)
    session.commit()
    text.normalized_text = "alterado"
    with pytest.raises(AppendOnlyViolation):
        session.commit()
```

- [ ] **Step 2: Run tests and confirm the schema failure**

Run: `cd apps/api && uv run python -m pytest tests/documents/test_models.py tests/normalization/test_normalize_record.py -v`

Expected: FAIL because the new metadata and document models do not exist.

- [ ] **Step 3: Implement academic metadata normalization**

Read `program`, `academic_program`, or `degree_program` without guessing from unrestricted prose. Read `knowledge_area`, `knowledge_areas`, or `area` as a normalized deduplicated tuple. Preserve missing values and add them to the normalization report; do not reject the production.

- [ ] **Step 4: Implement document models and migration `0011`**

Use named PostgreSQL enums and SQLite-compatible SQLAlchemy enums. Enforce unique `(production_version_id, version)` for text versions and `(document_text_version_id, page_number)` for pages. Register append-only listeners for text versions and pages. The downgrade drops dependent tables, columns, and enum types in reverse order.

- [ ] **Step 5: Verify migration and regression behavior**

Run:

```bash
cd apps/api
uv run python -m pytest tests/documents/test_models.py \
  tests/normalization tests/migrations/test_document_intelligence_migration.py -v
uv run python -m pytest tests/api/test_public_productions.py -v
uv run ruff check src tests
uv run mypy src
```

Expected: document rows are immutable, old records remain valid with null academic metadata, and the public production contract is unchanged.

- [ ] **Step 6: Commit the document schema**

```bash
git add apps/api/src/pci/models apps/api/src/pci/normalization \
  apps/api/alembic/versions/0011_document_intelligence.py \
  apps/api/tests/documents apps/api/tests/normalization \
  apps/api/tests/migrations/test_document_intelligence_migration.py
git commit -m "feat: model versioned document intelligence"
```

### Task 3: Acquire permitted PDFs and prepare page-preserving text

**Files:**
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/uv.lock`
- Modify: `apps/api/src/pci/storage/objects.py`
- Create: `apps/api/src/pci/documents/__init__.py`
- Create: `apps/api/src/pci/documents/contracts.py`
- Create: `apps/api/src/pci/documents/eligibility.py`
- Create: `apps/api/src/pci/documents/locators.py`
- Create: `apps/api/src/pci/documents/repository.py`
- Create: `apps/api/src/pci/documents/text.py`
- Create: `apps/api/src/pci/documents/service.py`
- Create: `apps/api/src/pci/documents/tasks.py`
- Modify: `apps/api/src/pci/worker.py`
- Modify: `apps/api/src/pci/productions/repository.py`
- Modify: `apps/api/src/pci/productions/service.py`
- Create: `apps/api/tests/documents/test_locators.py`
- Create: `apps/api/tests/documents/test_text_extraction.py`
- Create: `apps/api/tests/documents/test_service.py`
- Modify: `apps/api/tests/api/test_public_productions.py`

**Interfaces:**
- Extends `ObjectStore` with `get_object(key: str) -> bytes`; `S3ObjectStore` implements both read and write.
- Produces `DocumentLocation(url: str, media_type: str, rights: str | None)` and protocol `DocumentLocator.locate(raw: RawRecord) -> DocumentLocation | None`.
- Produces `CorpusEligibilityResult(eligible: bool, layer: Literal["analysis", "current"] | None, reasons: tuple[str, ...])` and `evaluate_corpus_eligibility(production_version: ProductionVersion, source: Source) -> CorpusEligibilityResult`.
- Produces `DspaceDocumentLocator`, which prefers direct same-origin PDF identifiers and otherwise parses a same-origin DSpace landing page.
- Produces `ExtractedPage(page_number: int, text: str)` and protocol `PdfTextExtractor.extract(content: bytes) -> tuple[ExtractedPage, ...]`.
- Produces `PyPdfTextExtractor` and `prepare_document_text(session, production_version_id, locator, object_store, extractor) -> DocumentPreparationResult`.
- Produces actor `prepare_document_text_task(production_version_id: str)` on queue `documents`.

- [ ] **Step 1: Write failing rights, locator, PDF, and fallback tests**

```python
def test_locator_rejects_cross_origin_and_non_pdf_links(raw_record) -> None:
    locator = DspaceDocumentLocator(http=fixture_http(
        '<a href="https://evil.example/file.pdf">PDF</a>'
        '<a href="/bitstream/123/1/readme.txt">texto</a>'
    ))
    assert locator.locate(raw_record) is None


def test_scanned_pdf_enters_ocr_queue_but_abstract_remains_usable(
    session, production_version_with_abstract, image_only_pdf, object_store
) -> None:
    result = prepare_document_text(
        session,
        production_version_with_abstract.id,
        locator=locator_for(image_only_pdf),
        object_store=object_store,
        extractor=PyPdfTextExtractor(),
    )
    assert result.source_document.status == SourceDocumentStatus.OCR_REQUIRED
    assert result.text_version.scope == DocumentTextScope.ABSTRACT_ONLY
```

Add cases for restricted rights, redirect to another host, response over the configured byte limit, wrong `Content-Type`, PDF magic mismatch, repeated text, Unicode offsets, and deterministic page boundaries.

Add eligibility cases proving that only theses/dissertations from sources configured as public institutions headquartered in Pernambuco enter processing; 2016–2025 returns layer `analysis`, 2026 returns `current`, and other types/years/institutions return explicit reasons without creating document work.

- [ ] **Step 2: Run document preparation tests and confirm failure**

Run: `cd apps/api && uv run python -m pytest tests/documents/test_locators.py tests/documents/test_text_extraction.py tests/documents/test_service.py -v`

Expected: FAIL because acquisition and extraction services do not exist.

- [ ] **Step 3: Implement bounded document acquisition**

Before locating a document, evaluate the production against source configuration keys `institution_sector=public`, `institution_state=PE`, `corpus_types=[thesis, dissertation]`, `analysis_year_start=2016`, `analysis_year_end=2025`, and `current_year=2026`. Reject missing or contradictory scope configuration safely. Then allow only `https` URLs on the repository host or an explicit per-source host allow-list. Stream downloads with a configured maximum of 100 MiB, a 30-second timeout, and at most two transient retries. Revalidate scheme and host after every redirect. Require PDF content type or `%PDF-` magic; never persist bytes when `RightsPolicy` is `METADATA_ONLY` or `LINK_ONLY`.

- [ ] **Step 4: Implement normalized text and fallback behavior**

Join pages with one newline while recording exact global offsets. Normalize line endings to `\n`, preserve Unicode characters, and calculate SHA-256 for the entire text and each page slice. Treat fewer than 200 non-whitespace characters across the PDF as `ocr_required`; create `abstract_only` text when an abstract exists. Record `restricted` or `failed` with a bounded error code, never a credential-bearing exception string.

- [ ] **Step 5: Wire the worker and live full-text projection**

Register the document actor in `pci.worker`. Update public production availability to consider a current `SourceDocument` in `text_extracted` or `ocr_required` state without modifying append-only `ProductionVersion` rows.

- [ ] **Step 6: Verify focused, worker, and regression checks**

Run:

```bash
cd apps/api
uv run python -m pytest tests/documents tests/storage tests/api/test_public_productions.py -v
uv run python -m pytest tests/test_worker.py tests/test_runtime_dependencies.py -v
uv run ruff check src tests
uv run mypy src
```

Expected: permitted searchable PDFs produce immutable page-aware text; scanned PDFs are queued; rights and host failures store no object bytes.

- [ ] **Step 7: Commit document acquisition**

```bash
git add apps/api
git commit -m "feat: prepare permitted thesis and dissertation text"
```

### Task 4: Create grounded private candidates through a provider-neutral extractor

**Files:**
- Create: `apps/api/src/pci/claims/__init__.py`
- Create: `apps/api/src/pci/claims/enums.py`
- Create: `apps/api/src/pci/claims/contracts.py`
- Create: `apps/api/src/pci/claims/providers.py`
- Create: `apps/api/src/pci/claims/repository.py`
- Create: `apps/api/src/pci/claims/service.py`
- Create: `apps/api/src/pci/claims/tasks.py`
- Create: `apps/api/src/pci/models/claims.py`
- Modify: `apps/api/src/pci/models/__init__.py`
- Modify: `apps/api/src/pci/settings.py`
- Modify: `apps/api/src/pci/worker.py`
- Create: `apps/api/alembic/versions/0012_candidate_extractions.py`
- Create: `apps/api/tests/claims/test_contracts.py`
- Create: `apps/api/tests/claims/test_extraction.py`
- Create: `apps/api/tests/claims/test_privacy.py`
- Create: `apps/api/tests/migrations/test_candidate_extraction_migration.py`

**Interfaces:**
- Produces `ContributionField` with exact values `problem_or_phenomenon`, `contribution_type`, `description`, `mechanism`, `population`, `service`, `territory`, `methodology`, `evidence_results`, `barriers_limitations`, `applicability`, `required_resources`, `maturity`, and `risks_contraindications`.
- Produces `ContributionType` with exact values `diagnosis`, `causal_explanation`, `method`, `intervention`, `technology`, `model`, `protocol`, `recommendation`, `evaluation`, and `instrument`.
- Produces `ExtractionRunStatus` with `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, and `SUPERSEDED`, plus `CandidateStatus` with `GENERATED`, `IN_REVIEW`, `ACCEPTED`, `REJECTED`, and `SUPERSEDED`.
- Produces `ExtractionDocument`, `GroundingPayload`, `CandidateClaimPayload`, `CandidateContributionPayload`, and `ProviderExtraction` Pydantic contracts with `extra="forbid"`.
- Produces protocol `ExtractionProvider.extract(document: ExtractionDocument) -> ProviderExtraction`.
- Produces `DeterministicExtractionProvider(fixtures: Mapping[str, ProviderExtraction])` and `HttpExtractionProvider(endpoint_url: str, api_key: str, model: str, timeout: float)`.
- Produces models `ExtractionRun`, `CandidateContribution`, `CandidateClaim`, and `CandidateGrounding`.
- Produces `run_extraction(session, document_text_version_id, provider, *, rerun: bool = False) -> ExtractionRun`.
- Produces actor `extract_document_task(document_text_version_id: str, rerun: bool = False)` on queue `claims`.

- [ ] **Step 1: Write failing contract, grounding, rerun, and privacy tests**

```python
def test_every_claim_must_match_its_exact_grounding(document, provider_payload) -> None:
    provider_payload.contributions[0].claims[0].groundings[0].quote = "texto inventado"
    with pytest.raises(InvalidGroundingError):
        validate_provider_extraction(document, provider_payload)


def test_explicit_rerun_preserves_and_supersedes_the_prior_run(session, ready_text) -> None:
    first = run_extraction(session, ready_text.id, deterministic_provider())
    second = run_extraction(session, ready_text.id, deterministic_provider(), rerun=True)
    assert first.id != second.id
    assert second.supersedes_id == first.id
    assert session.get(ExtractionRun, first.id) is first


def test_public_endpoints_never_serialize_candidate_marker(client, private_candidate) -> None:
    for path in ("/api/v1/productions", f"/api/v1/productions/{private_candidate.production_id}"):
        response = client.get(path)
        assert response.status_code == 200
        assert private_candidate.secret_marker not in response.text
```

- [ ] **Step 2: Run tests and confirm missing claims domain**

Run: `cd apps/api && uv run python -m pytest tests/claims -v`

Expected: FAIL because the claims contracts, models, and service do not exist.

- [ ] **Step 3: Implement strict provider contracts and validation**

Reject unknown fields, invalid contribution types, confidence outside `[0, 1]`, empty values, offsets outside the normalized text, a quote that does not exactly equal the referenced slice, a page outside the stored page range, and a grounding tied to another document version. Preserve the bounded raw provider response privately for reproducibility.

- [ ] **Step 4: Persist immutable runs, candidates, claims, and spans in migration `0012`**

An ordinary duplicate request returns the existing completed run for the same document checksum, provider, model, schema version, and instruction version. `rerun=True` creates a new run and a supersession link. Candidate scientific payload rows are append-only; operational run status may transition only through `queued -> running -> succeeded|failed`.

- [ ] **Step 5: Register deterministic and configurable HTTP providers**

Resolve the provider from settings inside the worker. The HTTP adapter posts only the versioned extraction contract, has bounded timeout/retries, redacts the API key from errors, and accepts no endpoint that is not HTTPS outside tests. A provider failure creates a private failed run and no candidate rows.

- [ ] **Step 6: Verify extraction and privacy**

Run:

```bash
cd apps/api
uv run python -m pytest tests/claims tests/api/test_metadata_visibility.py \
  tests/api/test_public_productions.py tests/test_worker.py -v
uv run ruff check src tests
uv run mypy src
```

Expected: deterministic candidates are reproducible and grounded; malformed or failed runs remain private; existing public JSON is unchanged.

- [ ] **Step 7: Commit private extraction**

```bash
git add apps/api
git commit -m "feat: extract grounded private contribution candidates"
```

### Task 5: Build the stratified review queue and independent assignments

**Files:**
- Create: `apps/api/src/pci/models/review.py`
- Modify: `apps/api/src/pci/models/__init__.py`
- Create: `apps/api/src/pci/review/__init__.py`
- Create: `apps/api/src/pci/review/repository.py`
- Create: `apps/api/src/pci/review/sampling.py`
- Create: `apps/api/src/pci/review/service.py`
- Create: `apps/api/alembic/versions/0013_review_sampling.py`
- Create: `apps/api/tests/review/test_sampling.py`
- Create: `apps/api/tests/review/test_assignments.py`
- Create: `apps/api/tests/migrations/test_review_sampling_migration.py`

**Interfaces:**
- Produces enums `SampleSplit` (`CALIBRATION`, `TEST`, `OPERATIONS`), `ReviewCaseKind` (`CANDIDATE`, `SOURCE_REVALIDATION`), `ReviewLane` (`SINGLE`, `PRIMARY`, `SECONDARY`, `ADJUDICATION`), and `ReviewStatus` (`PENDING`, `ASSIGNED`, `IN_REVIEW`, `COMPLETED`, `CANCELLED`).
- Produces models `SamplingRun`, `ReviewCase`, and `ReviewAssignment`.
- Produces `SamplingConfig(target_size: int, test_fraction: Decimal, double_code_fraction: Decimal, seed: str, rule_version: str)`.
- Produces `create_stratified_sample(session, candidate_ids: Sequence[UUID], config: SamplingConfig) -> SamplingRun`.
- Produces `claim_next_assignment(session, principal: AuthPrincipal) -> ReviewAssignment | None` with row locking and no double assignment.

- [ ] **Step 1: Write failing representativeness and concurrency tests**

```python
def test_stratified_sample_covers_each_available_stratum_before_refill(session, candidates) -> None:
    run = create_stratified_sample(
        session,
        [candidate.id for candidate in candidates],
        SamplingConfig(12, Decimal("0.25"), Decimal("0.20"), "thesis-seed", "v1"),
    )
    strata = {tuple(sorted(case.stratum.items())) for case in run.cases}
    assert strata.issuperset(expected_nonempty_strata(candidates))


def test_missing_area_is_preserved_as_not_informed_stratum(session, candidate_without_area) -> None:
    run = sample_one(session, candidate_without_area)
    assert run.cases[0].stratum["knowledge_area"] == "not_informed"
```

Add a PostgreSQL concurrency test proving two curators cannot claim the same assignment and a deterministic-seed test proving repeatable selection.

- [ ] **Step 2: Run review tests and confirm missing models**

Run: `cd apps/api && uv run python -m pytest tests/review -v`

Expected: FAIL because the review queue does not exist.

- [ ] **Step 3: Implement migration `0013` and sampling algorithm**

Define the stratum tuple as institution, first knowledge area or `not_informed`, publication year, thesis/dissertation type, `full_text|abstract_only`, and suggested contribution type. Within each stratum, order candidates by SHA-256 of `seed + candidate_id`; select round-robin across sorted strata before taking another item from any stratum. Persist the exact stratum, rule version, seed, split, and priority reason. A `CANDIDATE` case references one or more candidate contributions; a `SOURCE_REVALIDATION` case references one published contribution version. A database constraint requires exactly one of those targets.

- [ ] **Step 4: Implement single, double-blind, and adjudication assignments**

Normal cases receive one `SINGLE` assignment. The configured double-coded subset receives `PRIMARY` and `SECONDARY` assignments that cannot see each other's decisions; after both complete, create `ADJUDICATION`. Store actor identity only when an assignment is claimed, and prevent the same actor from holding both independent lanes.

- [ ] **Step 5: Verify sampling and queue safety**

Run:

```bash
cd apps/api
uv run python -m pytest tests/review tests/migrations/test_review_sampling_migration.py -v
uv run ruff check src tests
uv run mypy src
```

Expected: selection is representative, deterministic, auditable, and concurrency-safe.

- [ ] **Step 6: Commit the review queue**

```bash
git add apps/api
git commit -m "feat: add stratified scientific review queue"
```

### Task 6: Curate every field and materialize immutable contribution versions

**Files:**
- Create: `apps/api/src/pci/models/contributions.py`
- Modify: `apps/api/src/pci/models/review.py`
- Modify: `apps/api/src/pci/models/__init__.py`
- Create: `apps/api/src/pci/contributions/__init__.py`
- Create: `apps/api/src/pci/contributions/repository.py`
- Create: `apps/api/src/pci/contributions/service.py`
- Modify: `apps/api/src/pci/review/service.py`
- Create: `apps/api/alembic/versions/0014_scientific_contributions.py`
- Create: `apps/api/tests/contributions/test_field_decisions.py`
- Create: `apps/api/tests/contributions/test_versioning.py`
- Create: `apps/api/tests/contributions/test_four_eyes.py`
- Create: `apps/api/tests/migrations/test_scientific_contributions_migration.py`

**Interfaces:**
- Produces enums `FieldDecisionAction` (`ACCEPT`, `CORRECT`, `REJECT`, `INSUFFICIENT`) and `ContributionVersionStatus` (`DRAFT`, `VALIDATED`, `PUBLICATION_PENDING`, `PUBLISHED`, `SUPERSEDED`, `REVOKED`).
- Produces models `ScientificContribution`, `ContributionVersion`, `ContributionCandidateSource`, `ReviewFieldDecision`, and `ContributionGrounding`.
- Produces `record_field_decision(session, assignment_id, field, action, value, grounding_ids, reason, principal) -> ReviewFieldDecision`.
- Produces `complete_assignment(session, assignment_id, principal) -> ReviewAssignment`.
- Produces `materialize_validated_contribution(session, review_case_id, principal) -> ContributionVersion`.
- Produces `split_review_case(session: Session, review_case_id: UUID, partitions: Sequence[Sequence[UUID]], principal: AuthPrincipal) -> tuple[ReviewCase, ...]`.
- Produces `merge_review_cases(session: Session, review_case_ids: Sequence[UUID], principal: AuthPrincipal) -> ReviewCase`; all candidates must belong to the same `Production`.

- [ ] **Step 1: Write failing field completeness, provenance, split/merge, and immutability tests**

```python
def test_assignment_cannot_complete_until_every_governed_field_has_a_decision(
    session, partial_assignment, curator
) -> None:
    with pytest.raises(IncompleteReviewError) as error:
        complete_assignment(session, partial_assignment.id, curator)
    assert ContributionField.RISKS_CONTRAINDICATIONS in error.value.missing_fields


def test_corrected_value_requires_curator_grounding(session, assignment, curator) -> None:
    with pytest.raises(MissingGroundingError):
        record_field_decision(
            session, assignment.id, ContributionField.EVIDENCE_RESULTS,
            FieldDecisionAction.CORRECT, "Resultado corrigido", (), "Correção", curator,
        )


def test_validated_scientific_fields_are_immutable(session, validated_version) -> None:
    validated_version.description = "mudança silenciosa"
    with pytest.raises(ImmutableContributionError):
        session.flush()
```

Add tests that abstract-only groundings preserve the limitation, merge rejects candidates from different productions, independent assignments remain blind, and an adjudicated version records both source assignments.

- [ ] **Step 2: Run contribution tests and confirm missing domain**

Run: `cd apps/api && uv run python -m pytest tests/contributions -v`

Expected: FAIL because contribution models and services do not exist.

- [ ] **Step 3: Implement governed field decisions**

Require one latest decision for every `ContributionField`. `ACCEPT` uses the candidate value and grounding; `CORRECT` requires a bounded replacement value, at least one valid grounding, and a reason; `REJECT` and `INSUFFICIENT` require a reason and publish no value. Every correction adds a new decision sequence without deleting the prior decision.

- [ ] **Step 4: Materialize normalized contribution versions in migration `0014`**

Store each governed public value in an explicit nullable column on `ContributionVersion`; store type as `ContributionType`. A normal case materializes from its completed `SINGLE` assignment. A double-coded case materializes only from completed `ADJUDICATION`. Copy approved groundings to `ContributionGrounding`, including source scope, text version, page/section, offsets, quote, and quote hash.

- [ ] **Step 5: Enforce scientific immutability and four-eyes prerequisites**

Once status leaves `DRAFT`, prevent mutation of scientific columns and groundings. Corrections call `create_revision(contribution_id, base_version_id, principal)`, which creates a new draft and leaves the old row unchanged. Record all transitions in `AuditEvent` and expose `curator_actor_keys(version_id)` for publication checks.

- [ ] **Step 6: Verify contribution governance**

Run:

```bash
cd apps/api
uv run python -m pytest tests/contributions tests/review \
  tests/migrations/test_scientific_contributions_migration.py -v
uv run ruff check src tests
uv run mypy src
```

Expected: every field is decided, every published-capable value is grounded, versions are immutable after validation, and double-coded cases require adjudication.

- [ ] **Step 7: Commit contribution curation**

```bash
git add apps/api
git commit -m "feat: curate versioned scientific contributions"
```

### Task 7: Expose the internal curation and supervision API

**Files:**
- Create: `apps/api/src/pci/review/schemas.py`
- Create: `apps/api/src/pci/contributions/schemas.py`
- Create: `apps/api/src/pci/routers/__init__.py`
- Create: `apps/api/src/pci/routers/internal_contributions.py`
- Modify: `apps/api/src/pci/main.py`
- Create: `apps/api/tests/api/test_internal_review_api.py`
- Create: `apps/api/tests/api/test_internal_supervision_api.py`

**Interfaces:**
- Produces `GET /api/v1/internal/dashboard`.
- Produces admin-only `PUT /api/v1/internal/sources/{source_id}/processing-policy` and `POST /api/v1/internal/sampling-runs`; identity membership remains authoritative in the configured OIDC provider.
- Produces `GET /api/v1/internal/review-queue`, `POST /api/v1/internal/review-queue/claim`, and `GET /api/v1/internal/review-cases/{case_id}`.
- Produces `POST /api/v1/internal/review-assignments/{assignment_id}/field-decisions` and `POST /api/v1/internal/review-assignments/{assignment_id}/complete`.
- Produces `POST /api/v1/internal/review-cases/{case_id}/split`, `/merge`, and `/materialize`.
- Produces `GET /api/v1/internal/publication-queue` and contribution-version detail for supervisors; publication mutations are added in Task 8.
- All request and response schemas are internal-only and contain explicit `source_scope` and provenance fields.

- [ ] **Step 1: Write failing API authorization and transaction tests**

```python
def test_anonymous_user_cannot_read_review_queue(client) -> None:
    response = client.get("/api/v1/internal/review-queue")
    assert response.status_code == 401


def test_curator_correction_is_atomic(curator_client, assignment) -> None:
    response = curator_client.post(
        f"/api/v1/internal/review-assignments/{assignment.id}/field-decisions",
        json={
            "field": "evidence_results",
            "action": "correct",
            "value": "Resultado corrigido",
            "grounding_ids": ["not-a-uuid"],
            "reason": "Trecho anterior incompleto",
        },
    )
    assert response.status_code == 422
    assert decision_count(assignment.id) == 0
```

Add tests for bounded pagination, forbidden role, assignment ownership, blind secondary review, stale assignment conflict, no candidate data in supervisor list summaries, and rejection of incomplete or non-PE source policies.

- [ ] **Step 2: Run API tests and confirm missing routers**

Run: `cd apps/api && uv run python -m pytest tests/api/test_internal_review_api.py tests/api/test_internal_supervision_api.py -v`

Expected: FAIL with missing routes.

- [ ] **Step 3: Implement internal schemas and review endpoints**

Use service functions from Tasks 5–6; routers do not mutate models directly. Return 404 for a nonexistent or inaccessible assignment, 409 for stale state, 422 for invalid scientific input, and 403 for valid identity without the required role. Limit all text fields and reject unknown JSON properties.

- [ ] **Step 4: Implement dashboard and supervision reads**

Return counts for document states, extraction states, review queue, supervision queue, and publication projection failures. Supervisor details include validated values, human decisions, warnings, and public-safe source information, but never the provider raw response or hidden independent-review decisions. The admin source-policy endpoint validates the exact corpus and host-allow-list keys consumed by Task 3; the sampling endpoint records the immutable configuration from Task 5.

- [ ] **Step 5: Verify internal boundary and regressions**

Run:

```bash
cd apps/api
uv run python -m pytest tests/api/test_internal_review_api.py \
  tests/api/test_internal_supervision_api.py tests/auth tests/api/test_problem_api.py -v
uv run ruff check src tests
uv run mypy src
```

Expected: internal workflows require correct identity and role; failures roll back; public problem behavior remains unchanged.

- [ ] **Step 6: Commit internal APIs**

```bash
git add apps/api
git commit -m "feat: expose central scientific curation API"
```

### Task 8: Publish through a transactional outbox and safe public projection

**Files:**
- Create: `apps/api/src/pci/models/publication.py`
- Modify: `apps/api/src/pci/models/__init__.py`
- Create: `apps/api/src/pci/publication/__init__.py`
- Create: `apps/api/src/pci/publication/repository.py`
- Create: `apps/api/src/pci/publication/schemas.py`
- Create: `apps/api/src/pci/publication/service.py`
- Create: `apps/api/src/pci/publication/tasks.py`
- Create: `apps/api/src/pci/routers/public_contributions.py`
- Modify: `apps/api/src/pci/routers/internal_contributions.py`
- Modify: `apps/api/src/pci/main.py`
- Modify: `apps/api/src/pci/worker.py`
- Modify: `apps/api/src/pci/qualification/service.py`
- Create: `apps/api/alembic/versions/0015_publication_projection.py`
- Create: `apps/api/tests/publication/test_service.py`
- Create: `apps/api/tests/publication/test_outbox.py`
- Create: `apps/api/tests/api/test_public_contributions.py`
- Create: `apps/api/tests/migrations/test_publication_projection_migration.py`

**Interfaces:**
- Produces `PublicationAction` with `RETURN`, `PUBLISH`, `SUPERSEDE`, and `REVOKE`, plus `OutboxStatus` with `PENDING`, `PROCESSING`, `COMPLETED`, and `FAILED`.
- Produces models `PublicationDecision`, `PublicationOutbox`, and `PublishedContribution`.
- Produces `decide_publication(session, version_id, action, reason, supervisor) -> PublicationDecision`.
- Produces `process_publication_event(session, event_id) -> None` and actor `process_publication_event_task(event_id: str)` on queue `publication`.
- Produces `flag_contributions_for_source_review(session, production_id: UUID, reason: str) -> tuple[UUID, ...]`.
- Produces public routes `GET /api/v1/contributions` and `GET /api/v1/contributions/{contribution_id}`.
- Produces internal route `POST /api/v1/internal/contribution-versions/{version_id}/publication-decisions`.

- [ ] **Step 1: Write failing four-eyes, outbox, public-schema, and revocation tests**

```python
def test_curator_cannot_publish_the_version_they_validated(
    session, validated_version, curator_principal
) -> None:
    with pytest.raises(SeparationOfDutiesError):
        decide_publication(
            session, validated_version.id, PublicationAction.PUBLISH,
            "Aprovação", curator_principal,
        )


def test_duplicate_outbox_delivery_keeps_one_active_projection(session, publish_event) -> None:
    process_publication_event(session, publish_event.id)
    process_publication_event(session, publish_event.id)
    assert active_projection_count(publish_event.contribution_id) == 1


def test_public_detail_contains_no_private_candidate_fields(client, published_contribution) -> None:
    response = client.get(f"/api/v1/contributions/{published_contribution.id}")
    assert response.status_code == 200
    assert "confidence" not in response.text
    assert "provider_response" not in response.text
    assert "review_notes" not in response.text
```

Add tests for worker failure after inserting the projection, retry after lease expiry, out-of-order supersession, revocation, abstract-only label, source removal warning and review-case creation, bounded filters, and stable ordering.

- [ ] **Step 2: Run publication tests and confirm missing domain**

Run: `cd apps/api && uv run python -m pytest tests/publication tests/api/test_public_contributions.py -v`

Expected: FAIL because publication models and routes do not exist.

- [ ] **Step 3: Implement migration `0015` and supervisor decisions**

Create the decision and outbox rows in the same transaction as `publication_pending`. Require a nonblank reason for return, supersession, and revocation. Before publish/supersede, verify the supervisor actor key differs from every curator/adjudicator actor key and all required groundings still reference the same source version.

- [ ] **Step 4: Implement lease-safe idempotent projection**

Reuse the repository's established attempt-token/lease pattern: claim pending or expired events, upsert one public-safe projection per contribution version, deactivate the prior version on supersession/revocation, mark the outbox event complete, then transition the canonical version. If any step fails, keep the event retryable and never expose two active versions.

- [ ] **Step 5: Implement public list and detail schemas**

Serialize only validated scientific columns, approved groundings, public production metadata, validation/publication dates, version, and source availability. Provide filters for contribution type, institution, year, source scope, and production type. When qualification records a tombstone or a newer source version, mark affected projections with a source warning and create a review case through `flag_contributions_for_source_review`; do not silently reuse old intelligence. Do not add problem matching, paths, recommendations, or candidate-based fallback.

- [ ] **Step 6: Verify publication, privacy, and worker behavior**

Run:

```bash
cd apps/api
uv run python -m pytest tests/publication tests/api/test_public_contributions.py \
  tests/api/test_metadata_visibility.py tests/test_worker.py -v
uv run ruff check src tests
uv run mypy src
```

Expected: only supervisor-authorized active versions are public; retries converge; revocation removes the contribution; no private field is serialized.

- [ ] **Step 7: Commit publication governance**

```bash
git add apps/api
git commit -m "feat: publish validated scientific contributions safely"
```

### Task 9: Build the central-team review and supervision console

**Files:**
- Modify: `apps/web/package.json`
- Modify: `apps/web/package-lock.json`
- Create: `apps/web/src/lib/internal-auth.tsx`
- Create: `apps/web/src/lib/internal-api.ts`
- Create: `apps/web/src/app/equipe/page.tsx`
- Create: `apps/web/src/components/review/OperationsDashboard.tsx`
- Create: `apps/web/src/components/review/ReviewQueue.tsx`
- Create: `apps/web/src/components/review/ReviewWorkbench.tsx`
- Create: `apps/web/src/components/review/SupervisionWorkbench.tsx`
- Modify: `apps/web/src/app/globals.css`
- Create: `apps/web/src/components/review/ReviewWorkbench.test.tsx`
- Create: `apps/web/src/components/review/SupervisionWorkbench.test.tsx`

**Interfaces:**
- Produces `InternalAuthProvider` using configurable OIDC Authorization Code + PKCE and development-only local-token mode.
- Produces `InternalApi` matching Task 7–8 routes and injecting `Authorization: Bearer`.
- Produces `ReviewWorkbenchProps { case: ReviewCaseDetail; assignment: ReviewAssignmentDetail; api: InternalApi }`.
- Produces `SupervisionWorkbenchProps { version: SupervisionDetail; api: InternalApi }`.

- [ ] **Step 1: Write failing component security and usability tests**

```tsx
it("requires a foundation before accepting or correcting a field", async () => {
  render(<ReviewWorkbench case={reviewCase} assignment={assignment} api={api} />);
  await user.click(screen.getByRole("button", { name: "Aceitar campo" }));
  expect(await screen.findByText("Selecione ao menos um trecho de fundamento.")).toBeVisible();
  expect(api.decideField).not.toHaveBeenCalled();
});


it("prevents self-publication in the interface and explains the rule", () => {
  render(<SupervisionWorkbench version={versionValidatedByCurrentUser} api={api} />);
  expect(screen.getByRole("button", { name: "Publicar contribuição" })).toBeDisabled();
  expect(screen.getByText(/outra pessoa deve autorizar/i)).toBeVisible();
});
```

Add tests for abstract-only warning, source highlight, keyboard selection, preserved edits after API failure, hidden secondary review, return reason, revocation confirmation, and token absence from rendered text/logs.

- [ ] **Step 2: Run UI tests and confirm missing console**

Run: `cd apps/web && npm test -- ReviewWorkbench.test.tsx SupervisionWorkbench.test.tsx`

Expected: FAIL because the internal components do not exist.

- [ ] **Step 3: Add configurable OIDC client and internal API**

Use `oidc-client-ts` and `react-oidc-context`; store the user session in browser `sessionStorage`, use PKCE, and clear it on authentication error/logout. Permit a local token only when both `NODE_ENV=development` and `NEXT_PUBLIC_INTERNAL_AUTH_MODE=local`; production builds reject that configuration.

- [ ] **Step 4: Implement dashboard, queue, and side-by-side curation**

Show operational counts and queues, document/page navigation, candidate fields, confidence as an internal cue, exact grounding highlights, decision controls, history, and one-field-at-a-time validation. Preserve pending form state across recoverable request failures and announce errors through `role="alert"`.

- [ ] **Step 5: Implement supervision experience**

Show validated contribution, differences from candidates, approved groundings, warnings, actor separation, version history, and return/publish/supersede/revoke actions. Require typed confirmation for revocation and a nonblank reason where the API requires it.

- [ ] **Step 6: Verify frontend quality**

Run:

```bash
cd apps/web
npm test
npm run typecheck
npm run build
```

Expected: all component tests, type checking, and the production build pass.

- [ ] **Step 7: Commit the internal console**

```bash
git add apps/web
git commit -m "feat: add scientific curation console"
```

### Task 10: Present validated contributions publicly without restoring a catalog-first journey

**Files:**
- Create: `apps/web/src/lib/contribution-api.ts`
- Create: `apps/web/src/app/contribuicoes/[contributionId]/page.tsx`
- Create: `apps/web/src/components/contributions/ContributionDetail.tsx`
- Create: `apps/web/src/components/contributions/ContributionProvenance.tsx`
- Create: `apps/web/src/components/contributions/ContributionDetail.test.tsx`
- Modify: `apps/web/src/app/globals.css`

**Interfaces:**
- Produces `PublicContribution` mirroring the public API from Task 8 and `ContributionApi.get(contributionId: string) -> Promise<PublicContribution>`.
- Produces `ContributionDetail` organized around the five approved public questions.
- Does not modify `apps/web/src/app/page.tsx`; the homepage remains the problem assistant.

- [ ] **Step 1: Write failing public-language and provenance tests**

```tsx
it("presents a contribution as potentially useful, not as a guaranteed solution", () => {
  render(<ContributionDetail contribution={contribution} />);
  expect(screen.getByText(/contribuição potencialmente útil/i)).toBeVisible();
  expect(screen.queryByText(/resolve definitivamente/i)).not.toBeInTheDocument();
});


it("labels evidence derived only from the abstract", () => {
  render(<ContributionDetail contribution={abstractOnlyContribution} />);
  expect(screen.getByText("Evidência limitada ao resumo")).toBeVisible();
});
```

Add tests for unavailable source, revoked 404, version/date, keyboard-accessible provenance disclosure, and absence of internal confidence/review notes.

- [ ] **Step 2: Run the component test and confirm failure**

Run: `cd apps/web && npm test -- ContributionDetail.test.tsx`

Expected: FAIL because the contribution public components do not exist.

- [ ] **Step 3: Implement the public contribution contract and page**

Organize the page under: what it helps understand/do; related problem; evidence; application conditions; limits/risks/barriers. Show institution, thesis/dissertation source, validated/publication dates, active version, exact allowed quotation, location, rights/source warning, and original document link.

- [ ] **Step 4: Preserve the problem-first information architecture**

Do not add a contribution catalog to the homepage or replace `ProblemHandoff`. The public detail route is a foundation target for the future matching layer and may be reached by direct URL/API during this phase.

- [ ] **Step 5: Verify public UI and regressions**

Run:

```bash
cd apps/web
npm test
npm run typecheck
npm run build
```

Expected: the contribution page is accessible and evidence-led; the existing nine problem-flow tests remain green; the homepage still begins with the public problem.

- [ ] **Step 6: Commit the public contribution page**

```bash
git add apps/web
git commit -m "feat: present validated contributions publicly"
```

### Task 11: Instrument thesis evaluation and prove the vertical slice end to end

**Files:**
- Create: `apps/api/src/pci/evaluation/__init__.py`
- Create: `apps/api/src/pci/evaluation/schemas.py`
- Create: `apps/api/src/pci/evaluation/service.py`
- Modify: `apps/api/src/pci/routers/internal_contributions.py`
- Create: `apps/api/tests/evaluation/test_extraction_metrics.py`
- Create: `apps/api/tests/evaluation/test_governance_metrics.py`
- Create: `apps/api/tests/api/test_evaluation_export.py`
- Create: `apps/api/tests/api/test_contribution_governance_e2e.py`
- Create: `apps/web/e2e/contribution-governance.spec.ts`
- Modify: `infra/compose.yaml`
- Modify: `Makefile`
- Create: `scripts/verify-backup-restore.sh`
- Create: `apps/api/.env.example`
- Create: `apps/web/.env.example`
- Create: `docs/development/scientific-contribution-flow.md`

**Interfaces:**
- Produces `compute_extraction_metrics(session, sampling_run_id: UUID, split: SampleSplit) -> ExtractionMetrics` with per-field precision, recall, F1, unsupported-claim rate, and correction rate.
- Produces `compute_inter_rater_agreement(session, sampling_run_id: UUID) -> AgreementMetrics` for the double-coded subset, separated by governed field.
- Produces `compute_governance_metrics(session, sampling_run_id: UUID) -> GovernanceMetrics` with review time, return rate, publication time, provenance completeness, actor separation, and revocation visibility.
- Produces admin-only `GET /api/v1/internal/evaluation/sampling-runs/{run_id}.json` and `.csv`.

- [ ] **Step 1: Write failing metric and end-to-end tests**

```python
def test_metrics_keep_calibration_out_of_final_test(session, sampling_run) -> None:
    metrics = compute_extraction_metrics(session, sampling_run.id, SampleSplit.TEST)
    assert metrics.record_ids.isdisjoint(calibration_record_ids(sampling_run.id))


def test_complete_flow_never_exposes_candidate_before_supervisor_publication(
    client, curator_client, supervisor_client, deterministic_provider
) -> None:
    candidate = prepare_and_extract_fixture(deterministic_provider)
    assert client.get(f"/api/v1/contributions/{candidate.contribution_id}").status_code == 404
    validated = curate_all_fields(curator_client, candidate)
    assert client.get(f"/api/v1/contributions/{validated.contribution_id}").status_code == 404
    publish_and_project(supervisor_client, validated)
    assert client.get(f"/api/v1/contributions/{validated.contribution_id}").status_code == 200
```

Add tests for exact confusion counts, double-review agreement export, provenance completeness, revocation disappearance, CSV formula-injection neutralization, and authorization.

- [ ] **Step 2: Run evaluation and end-to-end tests and confirm failure**

Run: `cd apps/api && uv run python -m pytest tests/evaluation tests/api/test_evaluation_export.py tests/api/test_contribution_governance_e2e.py -v`

Expected: FAIL because evaluation services and exports do not exist.

- [ ] **Step 3: Implement derivable metrics and safe exports**

Treat completed adjudication or single review as the reference standard. For field-presence precision/recall, a candidate claim is the predicted positive and a final `ACCEPT` or `CORRECT` value is the reference positive; report accepted-without-correction and accepted-grounding rates separately from presence F1. Calculate metrics by governed field and stratum, compute agreement only from independent primary/secondary decisions before adjudication, keep calibration/test splits separate, and represent a zero denominator as `null`, not zero. Prefix spreadsheet-dangerous CSV cells beginning with `=`, `+`, `-`, or `@` with a single quote.

- [ ] **Step 4: Add configuration and operational documentation**

Document local signed-token creation, OIDC variables, extraction-provider variables, DSpace host allow-lists, document size/timeout settings, queue names, retry/recovery procedures, OCR handoff, publication recovery, backup/restore, and the distinction between metadata, private candidates, and public contributions. Keep secrets as placeholders. Add `backup-restore-smoke`, which uses a uniquely named temporary PostgreSQL database, verifies the five new revisions and a published fixture after restore, and always drops only that validated temporary database.

- [ ] **Step 5: Add the browser-level vertical slice**

Use deterministic fixture data and local test auth to validate curator review, supervisor publication by another identity, public contribution rendering, and subsequent revocation. Do not require an external identity or model provider in CI.

- [ ] **Step 6: Run the complete verification matrix**

Run:

```bash
make check
make backup-restore-smoke
cd apps/web && npm run test:e2e
cd ../api && uv run python -m pytest tests/api/test_contribution_governance_e2e.py -v
git diff --check
```

Expected: backend tests, Ruff, strict mypy, frontend tests/typecheck/build, runtime smoke, Compose validation, isolated backup/restore, Playwright, end-to-end governance, and whitespace checks all pass.

- [ ] **Step 7: Commit evaluation and operational proof**

```bash
git add apps/api apps/web infra/compose.yaml Makefile scripts/verify-backup-restore.sh \
  docs/development/scientific-contribution-flow.md
git commit -m "test: prove scientific contribution governance flow"
```

## Final Review Gate

After Task 11:

1. run the complete verification matrix again from a clean process;
2. compare every acceptance criterion in the phase-2 spec with at least one automated test or explicit manual check;
3. run `superpowers:requesting-code-review` on the whole branch;
4. fix all blocking findings and rerun affected plus full checks;
5. use `superpowers:verification-before-completion` before claiming success;
6. use `superpowers:finishing-a-development-branch` to choose merge, PR, or branch retention;
7. push only after GitHub authentication is available and confirmed.
