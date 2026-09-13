# Semantic Extraction and Central Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add private AI-assisted semantic extraction and a central-team workflow that validates every public problem, solution, evidence, barrier, applicability statement, and maturity assessment.

**Architecture:** Store AI output as private immutable drafts, decompose drafts into field-level validation items, and publish only approved semantic entities. Use OIDC-compatible authentication and role-based authorization for the internal API and console; retain complete decision and version history.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, PostgreSQL 17, Dramatiq, Redis, provider-neutral LLM interface, Next.js 15, React 19, TypeScript, Vitest, Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-08-pernambuco-ciencia-inovacao-design.md`

## Global Constraints

- Plan 1 must be complete and its public metadata contract must remain backward compatible.
- No AI-created semantic value may be returned by a public endpoint before human approval.
- Every approved semantic value must retain a source production, source version, exact evidence span, validator, decision time, and version.
- Human corrections override AI suggestions without deleting the original draft.
- The central platform team is the only validation authority.
- Validation occurs field by field and may validly conclude that an element is absent.
- Authentication is required only for internal routes; public consultation remains open.

---

## Repository Map Additions

```text
apps/api/src/pci/
  auth/
  semantics/
  taxonomies/
  validation/
apps/api/tests/
  auth/
  semantics/
  validation/
apps/web/
  src/app/admin/validation/
  src/components/validation/
  src/lib/internal-api.ts
```

### Task 1: Add versioned vocabularies and semantic entities

**Files:**
- Create: `apps/api/src/pci/models/taxonomy.py`
- Create: `apps/api/src/pci/models/semantics.py`
- Create: `apps/api/alembic/versions/0003_taxonomies_semantics.py`
- Create: `apps/api/src/pci/taxonomies/repository.py`
- Create: `apps/api/src/pci/taxonomies/service.py`
- Create: `apps/api/tests/models/test_semantic_schema.py`
- Create: `apps/api/tests/taxonomies/test_vocabulary_versioning.py`

**Interfaces:**
- Produces models: `Vocabulary`, `VocabularyVersion`, `Concept`, `ConceptLabel`, `ConceptRelation`
- Produces models: `Problem`, `Solution`, `Evidence`, `Barrier`, `Applicability`, `MaturityAssessment`, `SemanticLink`
- Produces: `TaxonomyService.resolve_label(vocabulary_code: str, label: str) -> Concept | None`
- Produces: `TaxonomyService.publish_version(vocabulary_id: UUID, actor_id: UUID) -> VocabularyVersion`

- [ ] **Step 1: Write failing semantic-integrity tests**

```python
def test_evidence_requires_production_solution_and_source_span(session) -> None:
    evidence = Evidence(
        production_id=production_id,
        solution_id=solution_id,
        statement="Reduziu perdas em 18%.",
        source_span_start=120,
        source_span_end=143,
        source_quote="redução de 18% nas perdas",
        visibility="private",
    )
    session.add(evidence)
    session.commit()
    assert evidence.solution_id == solution_id


def test_published_vocabulary_version_is_immutable(session, taxonomy_service) -> None:
    version = taxonomy_service.publish_version(vocabulary_id, actor_id)
    with pytest.raises(PublishedVersionError):
        taxonomy_service.rename_concept(version.id, concept_id, "Novo rótulo")
```

Add the required fixtures and imports in `apps/api/tests/conftest.py`.

- [ ] **Step 2: Run tests and confirm the missing-schema failure**

Run: `cd apps/api && python -m pytest tests/models/test_semantic_schema.py tests/taxonomies -v`

Expected: FAIL because the taxonomy and semantic models do not exist.

- [ ] **Step 3: Implement normalized, versioned semantic tables**

Every semantic entity stores `production_id`, `production_version_id`, `statement`, source-span offsets, source quote, validation status, visibility, created timestamp, and current version. `Evidence` additionally requires `solution_id`; `MaturityAssessment` requires `solution_id`, maturity concept, and rationale. `SemanticLink` stores typed relations such as `problem_addressed_by_solution`, `solution_supported_by_evidence`, and `solution_limited_by_barrier`.

Use this closed status set:

```python
class SemanticVisibility(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"


class ValidationStatus(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ABSENT = "absent"
    SUPERSEDED = "superseded"
```

Publishing a new vocabulary version copies prior concepts into a new draft version. Published versions are immutable; changes require another version.

- [ ] **Step 4: Apply the migration and verify constraints**

Run:

```bash
cd apps/api
alembic upgrade head
python -m pytest tests/models/test_semantic_schema.py tests/taxonomies -v
ruff check src tests
mypy src
```

Expected: all tests pass; evidence without a source span or solution fails database validation; published vocabularies cannot be mutated.

- [ ] **Step 5: Commit semantic foundations**

```bash
git add apps/api
git commit -m "feat: model versioned semantic intelligence"
```

### Task 2: Build the provider-neutral extraction pipeline

**Files:**
- Create: `apps/api/src/pci/semantics/contracts.py`
- Create: `apps/api/src/pci/semantics/prompts.py`
- Create: `apps/api/src/pci/semantics/providers/base.py`
- Create: `apps/api/src/pci/semantics/providers/fake.py`
- Create: `apps/api/src/pci/semantics/extraction.py`
- Create: `apps/api/src/pci/semantics/tasks.py`
- Create: `apps/api/src/pci/models/drafts.py`
- Create: `apps/api/alembic/versions/0004_semantic_drafts.py`
- Create: `apps/api/tests/semantics/test_extraction_contract.py`
- Create: `apps/api/tests/semantics/test_draft_privacy.py`

**Interfaces:**
- Produces: `EvidenceSpan(start: int, end: int, quote: str)`
- Produces: `DraftItem(kind: SemanticKind, statement: str, span: EvidenceSpan, confidence: float, concept_codes: tuple[str, ...])`
- Produces: `SemanticDraft(production_version_id: UUID, items: tuple[DraftItem, ...], model_name: str, prompt_version: str)`
- Produces: `SemanticExtractor.extract(document: ExtractionDocument) -> SemanticDraft`
- Produces: `extract_production(session: Session, production_version_id: UUID, extractor: SemanticExtractor) -> UUID`

- [ ] **Step 1: Write failing contract and privacy tests**

```python
def test_extractor_must_ground_every_item_in_document_text(fake_extractor, document) -> None:
    draft = fake_extractor.extract(document)
    assert draft.items
    for item in draft.items:
        assert document.text[item.span.start:item.span.end] == item.span.quote
        assert 0.0 <= item.confidence <= 1.0


def test_semantic_draft_never_appears_in_public_production(client, private_draft) -> None:
    response = client.get(f"/api/v1/productions/{private_draft.production_id}")
    assert response.status_code == 200
    serialized = response.text.lower()
    assert private_draft.secret_marker.lower() not in serialized
    assert "semantic_draft" not in serialized
```

- [ ] **Step 2: Run semantic pipeline tests and verify failure**

Run: `cd apps/api && python -m pytest tests/semantics -v`

Expected: FAIL because the extraction contracts and private draft storage do not exist.

- [ ] **Step 3: Implement grounded extraction and immutable drafts**

Define `SemanticKind` with values `problem`, `solution`, `evidence`, `barrier`, `applicability`, and `maturity`. The provider must return structured JSON validated by Pydantic. Reject an item when offsets are outside the document, the quote does not exactly match the source text, confidence is outside `[0,1]`, or a required field is absent.

Store the original provider response, normalized draft, model name, model revision, prompt version, input checksum, creation time, and execution status. Never update a draft in place; a rerun creates a new draft and supersedes the earlier one without deleting it.

The fake provider returns deterministic data from fixture markers so CI requires no network access or paid model.

- [ ] **Step 4: Verify the worker path and privacy boundary**

Run:

```bash
cd apps/api
alembic upgrade head
python -m pytest tests/semantics -v
python -m pytest tests/api/test_metadata_visibility.py -v
ruff check src tests
mypy src
```

Expected: valid grounded drafts are stored privately; malformed spans fail; the public API remains metadata-only.

- [ ] **Step 5: Commit extraction**

```bash
git add apps/api
git commit -m "feat: add grounded private semantic extraction"
```

### Task 3: Add internal authentication, roles, and workflow state

**Files:**
- Create: `apps/api/src/pci/auth/contracts.py`
- Create: `apps/api/src/pci/auth/oidc.py`
- Create: `apps/api/src/pci/auth/dependencies.py`
- Create: `apps/api/src/pci/models/users.py`
- Create: `apps/api/src/pci/models/validation.py`
- Create: `apps/api/alembic/versions/0005_users_validation.py`
- Create: `apps/api/src/pci/validation/state_machine.py`
- Create: `apps/api/tests/auth/test_internal_authorization.py`
- Create: `apps/api/tests/validation/test_state_machine.py`

**Interfaces:**
- Produces: `AuthPrincipal(subject: str, email: str, roles: frozenset[Role])`
- Produces roles: `ANALYST`, `CURATOR`, `SPECIALIST`, `SUPERVISOR`, `ADMIN`
- Produces: `require_roles(*roles: Role) -> Callable`
- Produces: `ValidationItem`, `ValidationDecision`, `ValidationAssignment`
- Produces: `transition(item: ValidationItem, action: ValidationAction, principal: AuthPrincipal) -> ValidationItem`

- [ ] **Step 1: Write failing role and state-transition tests**

```python
def test_public_user_cannot_read_validation_queue(client) -> None:
    response = client.get("/api/v1/internal/validation/items")
    assert response.status_code == 401


def test_curator_can_approve_but_analyst_cannot(validation_item) -> None:
    with pytest.raises(ForbiddenTransition):
        transition(validation_item, ValidationAction.APPROVE, analyst_principal())
    approved = transition(validation_item, ValidationAction.APPROVE, curator_principal())
    assert approved.status == ValidationStatus.APPROVED
```

- [ ] **Step 2: Run authorization and workflow tests and confirm failure**

Run: `cd apps/api && python -m pytest tests/auth tests/validation/test_state_machine.py -v`

Expected: FAIL because internal authentication and workflow rules are absent.

- [ ] **Step 3: Implement OIDC verification and explicit transitions**

Verify issuer, audience, signature, expiry, and subject from bearer JWTs. Map authorized group or role claims to the closed role enum. Tests override the verifier with signed local tokens; do not bypass dependencies in production code.

Implement transitions:

```text
not_submitted -> in_review       analyst, curator, specialist
in_review -> approved            curator, specialist, supervisor
in_review -> rejected            curator, specialist, supervisor
in_review -> absent              curator, specialist, supervisor
rejected -> in_review            curator, specialist, supervisor
approved -> superseded           supervisor
absent -> superseded             supervisor
```

Every transition creates `ValidationDecision` containing previous status, next status, actor, role, reason, timestamp, and source-span snapshot. Require a nonempty reason for `rejected`, `absent`, and `superseded`.

- [ ] **Step 4: Run security and transition checks**

Run:

```bash
cd apps/api
alembic upgrade head
python -m pytest tests/auth tests/validation/test_state_machine.py -v
ruff check src tests
mypy src
```

Expected: unauthorized access returns 401; insufficient roles return 403; illegal transitions leave state unchanged and create no decision row.

- [ ] **Step 5: Commit validation security**

```bash
git add apps/api
git commit -m "feat: secure central validation workflow"
```

### Task 4: Implement the validation API and central-team console

**Files:**
- Create: `apps/api/src/pci/validation/schemas.py`
- Create: `apps/api/src/pci/validation/repository.py`
- Create: `apps/api/src/pci/validation/service.py`
- Create: `apps/api/src/pci/validation/router.py`
- Modify: `apps/api/src/pci/main.py`
- Create: `apps/api/tests/validation/test_validation_api.py`
- Create: `apps/web/package.json`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/next.config.ts`
- Create: `apps/web/postcss.config.mjs`
- Create: `apps/web/vitest.config.ts`
- Create: `apps/web/playwright.config.ts`
- Create: `apps/web/src/app/layout.tsx`
- Create: `apps/web/src/app/globals.css`
- Create: `apps/web/src/middleware.ts`
- Create: `apps/web/src/app/admin/validation/page.tsx`
- Create: `apps/web/src/app/admin/validation/[itemId]/page.tsx`
- Create: `apps/web/src/components/validation/ValidationWorkbench.tsx`
- Create: `apps/web/src/lib/auth.ts`
- Create: `apps/web/src/lib/internal-api.ts`
- Create: `apps/web/src/components/validation/ValidationWorkbench.test.tsx`
- Create: `apps/web/tests/e2e/validation-workbench.spec.ts`

**Interfaces:**
- Produces: `GET /api/v1/internal/validation/items`
- Produces: `GET /api/v1/internal/validation/items/{item_id}`
- Produces: `POST /api/v1/internal/validation/items/{item_id}/decisions`
- Produces: `ValidationWorkbenchProps { item: ValidationItemDetail; onDecision(input: DecisionInput): Promise<void> }`
- Consumes: authentication and validation types from Task 3; semantic drafts from Task 2

- [ ] **Step 1: Write failing API and component tests**

```python
def test_approve_edited_item_records_human_value_and_reason(curator_client, review_item) -> None:
    response = curator_client.post(
        f"/api/v1/internal/validation/items/{review_item.id}/decisions",
        json={
            "action": "approve",
            "statement": "Solução corrigida pela curadoria.",
            "source_span_start": 30,
            "source_span_end": 67,
            "source_quote": "trecho integral que fundamenta a solução",
            "reason": "A proposta automática omitiu a condição de aplicação.",
            "concept_codes": ["solution:process"],
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["statement"] == "Solução corrigida pela curadoria."
```

```tsx
it("requires a source quote before approval", async () => {
  render(<ValidationWorkbench item={itemWithoutQuote} onDecision={onDecision} />);
  await userEvent.click(screen.getByRole("button", { name: "Aprovar" }));
  expect(await screen.findByText("Selecione o trecho que fundamenta a decisão.")).toBeVisible();
  expect(onDecision).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run API and UI tests and confirm failure**

Run:

```bash
cd apps/api && python -m pytest tests/validation/test_validation_api.py -v
cd ../web && pnpm vitest run src/components/validation/ValidationWorkbench.test.tsx
```

Expected: FAIL because routes, pages, and components do not exist.

- [ ] **Step 3: Implement queue, workbench, and decision submission**

The queue supports filters for semantic kind, status, area, institution, production type, period, territorial universe, assignee, and age. The detail response returns source text, metadata, AI suggestion, confidence, concept candidates, current assignment, and decision history.

Render source content and proposed fields side by side. Support selecting a source span, editing the statement, choosing controlled concepts, and performing `approve`, `reject`, or `absent`. Disable submission without a valid source span for approved content. After success, invalidate the queue item and navigate to the next assigned item.

Initialize the web package with Next.js, React, TypeScript, Tailwind CSS, Vitest, Testing Library, Playwright, `@axe-core/playwright`, and `oidc-client-ts`. Configure the test runner for `jsdom`, define the `@/` source alias, and make the root layout render a skip link and `<main id="main-content">` landmark. Protect `/admin/*` in middleware, obtain an OIDC access token through `auth.ts`, and attach it only to internal API calls; tests use a signed local token provider.

- [ ] **Step 4: Run validation API, UI, and browser tests**

Run:

```bash
cd apps/api && python -m pytest tests/validation -v
cd ../web && pnpm vitest run
pnpm playwright test tests/e2e/validation-workbench.spec.ts
```

Expected: tests pass; the browser scenario signs in as curator, edits one proposal, selects its source span, approves it, and sees the immutable history entry.

- [ ] **Step 5: Commit the central console**

```bash
git add apps/api apps/web
git commit -m "feat: add central semantic validation console"
```

### Task 5: Enforce publication gates, audit history, and revalidation

**Files:**
- Create: `apps/api/src/pci/semantics/publication.py`
- Create: `apps/api/src/pci/semantics/public_views.py`
- Create: `apps/api/src/pci/validation/revalidation.py`
- Create: `apps/api/alembic/versions/0006_public_semantic_views.py`
- Modify: `apps/api/src/pci/productions/schemas.py`
- Modify: `apps/api/src/pci/productions/service.py`
- Create: `apps/api/tests/semantics/test_publication_gate.py`
- Create: `apps/api/tests/validation/test_revalidation.py`
- Create: `apps/api/tests/audit/test_validation_history.py`

**Interfaces:**
- Produces: `publish_validation_item(session: Session, item_id: UUID, principal: AuthPrincipal) -> PublishedSemanticEntity`
- Produces: `reopen_impacted_items(session: Session, event: RevalidationEvent) -> int`
- Produces public response field: `validated_intelligence` containing only approved public entities
- Consumes: validation decisions, semantic entities, vocabulary versions, and production versions

- [ ] **Step 1: Write failing publication and revalidation tests**

```python
def test_only_supervisor_can_publish_an_approved_human_validation(
    session, draft_item, curator, supervisor
) -> None:
    with pytest.raises(PublicationBlocked):
        publish_validation_item(session, draft_item.id, supervisor)
    approved = approve_item(session, draft_item.id, curator)
    with pytest.raises(ForbiddenPublication):
        publish_validation_item(session, approved.id, curator)
    published = publish_validation_item(session, approved.id, supervisor)
    assert published.visibility == SemanticVisibility.PUBLIC
    assert published.validated_by == curator.subject
    assert published.published_by == supervisor.subject


def test_new_production_version_reopens_published_items(session, published_solution) -> None:
    count = reopen_impacted_items(session, production_version_event(published_solution.production_id))
    assert count == 1
    assert published_solution.validation_status == ValidationStatus.APPROVED
    assert published_solution.review_pending is True
```

- [ ] **Step 2: Run gate tests and confirm failure**

Run: `cd apps/api && python -m pytest tests/semantics/test_publication_gate.py tests/validation/test_revalidation.py tests/audit -v`

Expected: FAIL because publication and revalidation services do not exist.

- [ ] **Step 3: Implement the database and service-level gate**

Create a database view that selects semantic entities only when `validation_status='approved'`, `visibility='public'`, `validated_by IS NOT NULL`, `published_by IS NOT NULL`, and a valid source span exists. Only a supervisor may execute publication. The service must check the same invariants before changing visibility, making accidental bypass fail at both layers.

When a production version, source text, vocabulary concept, extraction prompt, or validation policy changes, create revalidation items and set `review_pending=true` on affected public entities. Keep the last approved version visible while review is pending. Only after a replacement is approved and published should the service mark the prior version `superseded`; a supervisor may withdraw it earlier only when the underlying evidence became invalid.

- [ ] **Step 4: Run the full Plan 2 verification suite**

Run:

```bash
cd apps/api
alembic upgrade head
python -m pytest -v
ruff check src tests
mypy src
cd ../web
pnpm vitest run
pnpm playwright test tests/e2e/validation-workbench.spec.ts
```

Expected: all checks pass; no unapproved draft is serialized publicly; every public semantic entity resolves to an immutable human decision and source span.

- [ ] **Step 5: Commit the complete validation boundary**

```bash
git add apps/api apps/web
git commit -m "feat: enforce human-gated semantic publication"
```

## Plan 2 Completion Gate

- AI extraction is grounded, typed, private, provider-neutral, and reproducible.
- Internal routes require valid identity and role.
- Central-team members validate individual semantic dimensions.
- The public database view and service both reject unvalidated content.
- Every decision and prior draft remains auditable.
- Source, vocabulary, or policy changes trigger controlled revalidation.
