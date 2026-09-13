# Public Problem Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the open public experience that interprets a problem in natural language and retrieves validated solutions, evidence, barriers, competencies, productions, and territories with explainable ranking and citations.

**Architecture:** Build hybrid retrieval over PostgreSQL full-text search and pgvector embeddings, merge results through a deterministic ranking service, and expose them through public FastAPI endpoints and a responsive Next.js application. A grounded-answer service may synthesize only approved semantic records returned by retrieval.

**Tech Stack:** Python 3.12, FastAPI, PostgreSQL 17, pgvector, SQLAlchemy 2, provider-neutral embeddings and text generation, Next.js 15, React 19, TypeScript, Tailwind CSS, Vitest, Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-08-pernambuco-ciencia-inovacao-design.md`

## Global Constraints

- Plans 1 and 2 must be complete.
- Public browsing and search require no login.
- Search and answers may use only metadata-public records and approved semantic entities.
- Every synthesized statement must cite retrievable productions and source spans.
- The user must be able to switch between `produced_in_pe`, `about_pe`, and both without collapsing the two relations.
- Ranking factors and contribution scores must be returned to the client.
- A no-evidence response is preferable to an unsupported answer.
- Public pages must be responsive, keyboard operable, and testable without live AI providers.

---

## Repository Map Additions

```text
apps/api/src/pci/
  search/
  answers/
  feedback/
apps/api/tests/
  search/
  answers/
  feedback/
apps/web/src/
  app/(public)/
  components/search/
  components/results/
  components/details/
  lib/public-api.ts
```

### Task 1: Build reconstructible lexical and vector indexes

**Files:**
- Create: `apps/api/src/pci/search/contracts.py`
- Create: `apps/api/src/pci/search/embeddings/base.py`
- Create: `apps/api/src/pci/search/embeddings/fake.py`
- Create: `apps/api/src/pci/search/indexing.py`
- Create: `apps/api/src/pci/search/repository.py`
- Create: `apps/api/alembic/versions/0007_search_index.py`
- Create: `apps/api/tests/search/test_indexing_visibility.py`
- Create: `apps/api/tests/search/test_rebuild_index.py`

**Interfaces:**
- Produces: `EmbeddingProvider.embed(text: str) -> list[float]`
- Produces: `SearchDocument(id: UUID, entity_type: str, text: str, metadata: dict[str, Any], embedding: list[float])`
- Produces: `index_production(session: Session, production_id: UUID, embedder: EmbeddingProvider) -> int`
- Produces: `rebuild_search_index(session: Session, embedder: EmbeddingProvider) -> RebuildResult`

- [ ] **Step 1: Write failing visibility and rebuild tests**

```python
def test_index_contains_public_metadata_and_only_approved_semantics(session, embedder, records) -> None:
    count = index_production(session, records.production_id, embedder)
    documents = list_search_documents(session, records.production_id)
    assert count == 2
    assert {doc.entity_type for doc in documents} == {"production", "solution"}
    assert records.private_draft_marker not in " ".join(doc.text for doc in documents)


def test_rebuild_produces_same_document_ids(session, embedder, indexed_records) -> None:
    before = sorted(doc.id for doc in all_search_documents(session))
    truncate_search_index(session)
    rebuild_search_index(session, embedder)
    after = sorted(doc.id for doc in all_search_documents(session))
    assert after == before
```

- [ ] **Step 2: Run index tests and verify failure**

Run: `cd apps/api && python -m pytest tests/search/test_indexing_visibility.py tests/search/test_rebuild_index.py -v`

Expected: FAIL because the index schema and services do not exist.

- [ ] **Step 3: Implement the hybrid index projection**

Create `search_documents` with stable derived ID, entity type, entity ID, production ID, text, weighted `tsvector`, vector embedding, filter metadata JSON, source version, validation version, and indexed timestamp. Build text from public title, abstract, keywords, approved problem, solution, evidence, barrier, applicability, and concept labels; do not include private drafts or internal comments.

The fake embedder hashes normalized tokens into a deterministic 64-dimensional vector for tests. Production uses a configured provider behind the same interface. Rebuilding truncates only the derived index and reconstructs it from canonical public views.

- [ ] **Step 4: Apply migrations and verify deterministic reconstruction**

Run:

```bash
cd apps/api
alembic upgrade head
python -m pytest tests/search/test_indexing_visibility.py tests/search/test_rebuild_index.py -v
ruff check src tests
mypy src
```

Expected: tests pass; repeated rebuilds yield identical derived IDs and contain no private marker.

- [ ] **Step 5: Commit search indexing**

```bash
git add apps/api
git commit -m "feat: add reconstructible hybrid search index"
```

### Task 2: Interpret problems and implement explainable hybrid ranking

**Files:**
- Create: `apps/api/src/pci/search/query.py`
- Create: `apps/api/src/pci/search/ranking.py`
- Create: `apps/api/src/pci/search/service.py`
- Create: `apps/api/src/pci/search/schemas.py`
- Create: `apps/api/src/pci/search/router.py`
- Modify: `apps/api/src/pci/main.py`
- Create: `apps/api/tests/search/test_problem_interpretation.py`
- Create: `apps/api/tests/search/test_hybrid_ranking.py`
- Create: `apps/api/tests/search/test_search_api.py`

**Interfaces:**
- Produces: `ProblemQuery(text: str, concepts: tuple[str, ...], territory_relation: TerritoryRelation | None, territory_codes: tuple[str, ...], audience_codes: tuple[str, ...], sector_codes: tuple[str, ...])`
- Produces: `SearchFilters`
- Produces: `RankExplanation(semantic: float, lexical: float, evidence: float, maturity: float, territory: float, total: float)`
- Produces: `SearchService.interpret(text: str) -> ProblemQuery`
- Produces: `SearchService.search(query: ProblemQuery, filters: SearchFilters, page: int, page_size: int) -> SearchPage`
- Produces: `POST /api/v1/search/interpret` and `POST /api/v1/search`

- [ ] **Step 1: Write failing interpretation and ranking tests**

```python
def test_interpretation_preserves_user_text_and_returns_editable_concepts(service) -> None:
    query = service.interpret("Como reduzir perdas de água no semiárido?")
    assert query.text == "Como reduzir perdas de água no semiárido?"
    assert "problem:water_loss" in query.concepts
    assert "territory:semiarid" in query.territory_codes


def test_hybrid_score_is_explainable_and_filter_is_strict(search_service) -> None:
    page = search_service.search(
        ProblemQuery(text="saneamento rural", concepts=("problem:sanitation",)),
        SearchFilters(territory_relation="about_pe", production_types=("article",)),
        page=1,
        page_size=10,
    )
    assert page.items
    assert all(item.territory_relation == "about_pe" for item in page.items)
    assert all(item.production_type == "article" for item in page.items)
    assert page.items[0].rank.total == pytest.approx(
        0.45 * page.items[0].rank.semantic
        + 0.20 * page.items[0].rank.lexical
        + 0.15 * page.items[0].rank.evidence
        + 0.10 * page.items[0].rank.maturity
        + 0.10 * page.items[0].rank.territory
    )
```

- [ ] **Step 2: Run search-service tests and confirm failure**

Run: `cd apps/api && python -m pytest tests/search/test_problem_interpretation.py tests/search/test_hybrid_ranking.py tests/search/test_search_api.py -v`

Expected: FAIL because interpretation, ranking, and endpoints do not exist.

- [ ] **Step 3: Implement interpretation, retrieval, filters, and rank explanations**

Interpretation uses controlled vocabularies plus semantic similarity and returns suggestions without silently rewriting the original query. The public client must explicitly submit the interpreted query.

Retrieve lexical and vector candidates separately, normalize component scores to `[0,1]`, enforce filters before final ranking, and calculate:

```python
total = (
    0.45 * semantic
    + 0.20 * lexical
    + 0.15 * evidence
    + 0.10 * maturity
    + 0.10 * territory
)
```

Return each component and a short explanation. Add facets for area, institution, production type, period, maturity, territorial relation, and validation date. Use stable tie-breaking by total score, evidence score, publication date, and entity ID.

- [ ] **Step 4: Verify public search behavior**

Run:

```bash
cd apps/api
python -m pytest tests/search -v
ruff check src tests
mypy src
```

Expected: tests pass; filters are strict; scores are repeatable; empty result sets return 200 with `items: []` and refinement suggestions, not fabricated matches.

- [ ] **Step 5: Commit explainable search**

```bash
git add apps/api
git commit -m "feat: interpret problems and rank validated solutions"
```

### Task 3: Build the public problem-search journey

**Files:**
- Create: `apps/web/src/app/(public)/layout.tsx`
- Create: `apps/web/src/app/(public)/page.tsx`
- Create: `apps/web/src/app/(public)/buscar/page.tsx`
- Create: `apps/web/src/components/search/ProblemSearchForm.tsx`
- Create: `apps/web/src/components/search/InterpretedProblem.tsx`
- Create: `apps/web/src/components/results/SearchResults.tsx`
- Create: `apps/web/src/components/results/ResultCard.tsx`
- Create: `apps/web/src/components/results/FilterPanel.tsx`
- Create: `apps/web/src/lib/public-api.ts`
- Create: `apps/web/src/components/search/ProblemSearchForm.test.tsx`
- Create: `apps/web/tests/e2e/public-search.spec.ts`

**Interfaces:**
- Produces: public routes `/` and `/buscar`
- Produces: `ProblemSearchFormProps { initialText?: string; onInterpret(query: ProblemQuery): Promise<void> }`
- Produces: `SearchResultsProps { page: SearchPage; onFiltersChange(filters: SearchFilters): void }`
- Consumes: Plan 3 Task 2 public search contracts

- [ ] **Step 1: Write failing component and journey tests**

```tsx
it("shows the interpreted problem before running the search", async () => {
  render(<ProblemSearchForm onInterpret={onInterpret} />);
  await userEvent.type(screen.getByLabelText("Descreva o problema"), "Como reduzir perdas de água?");
  await userEvent.click(screen.getByRole("button", { name: "Interpretar problema" }));
  expect(await screen.findByText("Confira como entendemos seu problema")).toBeVisible();
  expect(screen.getByRole("button", { name: "Buscar soluções" })).toBeVisible();
});
```

```ts
test("a visitor searches without authentication and switches territorial universe", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Descreva o problema").fill("Como reduzir perdas de água no semiárido?");
  await page.getByRole("button", { name: "Interpretar problema" }).click();
  await page.getByRole("button", { name: "Buscar soluções" }).click();
  await expect(page.getByRole("heading", { name: "Soluções encontradas" })).toBeVisible();
  await page.getByLabel("Universo territorial").selectOption("about_pe");
  await expect(page.getByText("Ciência sobre Pernambuco")).toBeVisible();
});
```

- [ ] **Step 2: Run frontend tests and confirm failure**

Run:

```bash
cd apps/web
pnpm vitest run src/components/search/ProblemSearchForm.test.tsx
pnpm playwright test tests/e2e/public-search.spec.ts
```

Expected: FAIL because public routes and components do not exist.

- [ ] **Step 3: Implement the responsive, accessible search pages**

The home page contains one dominant problem text area, examples from multiple knowledge areas, and a plain-language explanation of validated intelligence. After interpretation, render removable concept chips and editable territory, audience, and sector controls. Search results use tabs `Soluções`, `Evidências`, `Barreiras`, `Competências`, and `Produções` while preserving one filter state in the URL.

Each result card displays title, solution type, maturity, institution, territorial relation, evidence count, validation status, and an expandable “Por que apareceu?” panel populated from `RankExplanation`. All controls require labels, visible focus, keyboard access, and loading and empty states.

- [ ] **Step 4: Run component, browser, and accessibility checks**

Run:

```bash
cd apps/web
pnpm vitest run
pnpm playwright test tests/e2e/public-search.spec.ts
pnpm lint
pnpm typecheck
```

Expected: all checks pass; the journey works without an auth cookie; keyboard-only navigation reaches interpretation, filters, results, and details in logical order.

- [ ] **Step 5: Commit the public search journey**

```bash
git add apps/web
git commit -m "feat: add public problem-driven discovery journey"
```

### Task 4: Add solution, production, competence, comparison, and territory views

**Files:**
- Create: `apps/api/src/pci/search/details.py`
- Create: `apps/api/src/pci/search/details_router.py`
- Create: `apps/api/tests/search/test_public_details.py`
- Create: `apps/web/src/app/(public)/solucoes/[id]/page.tsx`
- Create: `apps/web/src/app/(public)/producoes/[id]/page.tsx`
- Create: `apps/web/src/app/(public)/competencias/[id]/page.tsx`
- Create: `apps/web/src/app/(public)/territorio/page.tsx`
- Create: `apps/web/src/app/(public)/comparar/page.tsx`
- Create: `apps/web/src/components/details/EvidencePanel.tsx`
- Create: `apps/web/src/components/details/SourceSpan.tsx`
- Create: `apps/web/src/components/details/SolutionComparison.tsx`
- Create: `apps/web/tests/e2e/public-details.spec.ts`

**Interfaces:**
- Produces: `GET /api/v1/solutions/{id}`
- Produces: `GET /api/v1/competences/{id}`
- Produces: `GET /api/v1/territories/{code}/overview`
- Produces: `POST /api/v1/solutions/compare`
- Consumes: public metadata and approved semantic views only

- [ ] **Step 1: Write failing detail and comparison tests**

```python
def test_solution_detail_contains_evidence_barriers_and_source_spans(client, public_solution) -> None:
    response = client.get(f"/api/v1/solutions/{public_solution.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["evidence"][0]["source_quote"]
    assert body["barriers"][0]["validation"]["status"] == "approved"
    assert body["production"]["source_url"].startswith("https://")


def test_comparison_rejects_private_or_unknown_solution(client, public_solution, private_solution) -> None:
    response = client.post("/api/v1/solutions/compare", json={"ids": [str(public_solution.id), str(private_solution.id)]})
    assert response.status_code == 404
```

- [ ] **Step 2: Run detail tests and confirm failure**

Run: `cd apps/api && python -m pytest tests/search/test_public_details.py -v`

Expected: FAIL because the public detail services and routes do not exist.

- [ ] **Step 3: Implement public detail contracts and pages**

Solution pages show problem addressed, statement, type, maturity, evidence, barriers, applicability, territories, linked productions, competencies, validation date, and source spans. Production pages clearly separate collected metadata from validated intelligence. Competence profiles aggregate only public productions and approved semantic links. Territory overviews return counts split by territorial relation.

Comparison accepts two to four public solution IDs and returns common dimensions: evidence, barriers, applicability, maturity, territory, organizations, and production dates. Use `null` plus a visible “não informado” label for missing dimensions; never infer a comparison value.

- [ ] **Step 4: Run API and browser detail tests**

Run:

```bash
cd apps/api && python -m pytest tests/search/test_public_details.py -v
cd ../web && pnpm playwright test tests/e2e/public-details.spec.ts
pnpm vitest run
pnpm typecheck
```

Expected: all tests pass; private entities return 404; every visible evidence item opens its source production and quoted span context.

- [ ] **Step 5: Commit public details**

```bash
git add apps/api apps/web
git commit -m "feat: expose validated solution and competence views"
```

### Task 5: Add grounded answers and usefulness feedback

**Files:**
- Create: `apps/api/src/pci/answers/contracts.py`
- Create: `apps/api/src/pci/answers/providers/base.py`
- Create: `apps/api/src/pci/answers/providers/fake.py`
- Create: `apps/api/src/pci/answers/service.py`
- Create: `apps/api/src/pci/answers/router.py`
- Create: `apps/api/src/pci/feedback/models.py`
- Create: `apps/api/src/pci/feedback/router.py`
- Create: `apps/api/alembic/versions/0008_search_feedback.py`
- Create: `apps/api/tests/answers/test_grounded_answer.py`
- Create: `apps/api/tests/answers/test_no_evidence_answer.py`
- Create: `apps/api/tests/feedback/test_public_feedback.py`
- Create: `apps/web/src/components/results/GroundedAnswer.tsx`
- Create: `apps/web/src/components/results/UsefulnessFeedback.tsx`

**Interfaces:**
- Produces: `GroundedAnswer(text: str, citations: tuple[Citation, ...], limitations: tuple[str, ...], evidence_sufficient: bool)`
- Produces: `GroundedAnswerService.answer(query: ProblemQuery, search_page: SearchPage) -> GroundedAnswer`
- Produces: `POST /api/v1/answers`
- Produces: `POST /api/v1/feedback/usefulness`
- Consumes: approved search results and exact source spans

- [ ] **Step 1: Write failing grounding and no-evidence tests**

```python
def test_every_answer_claim_has_a_retrievable_citation(answer_service, validated_results) -> None:
    answer = answer_service.answer(problem_query(), validated_results)
    assert answer.evidence_sufficient is True
    assert answer.citations
    for citation in answer.citations:
        assert citation.production_id
        assert citation.source_quote
        assert citation.validation_status == "approved"


def test_no_validated_evidence_returns_limitation_not_generated_advice(answer_service) -> None:
    answer = answer_service.answer(problem_query(), empty_search_page())
    assert answer.evidence_sufficient is False
    assert answer.text == "Ainda não há evidência validada suficiente para responder a este problema."
    assert answer.citations == ()
```

- [ ] **Step 2: Run answer and feedback tests and confirm failure**

Run: `cd apps/api && python -m pytest tests/answers tests/feedback -v`

Expected: FAIL because answer and feedback modules do not exist.

- [ ] **Step 3: Implement citation-constrained synthesis and feedback capture**

Pass only approved search snippets to the answer provider. Require the provider to return claims referencing supplied citation IDs. Reject unknown citations, empty quotes, or claims without citations. On rejection, return the deterministic no-evidence response and record a safe operational error without exposing provider content.

Feedback accepts search session ID, optional result ID, usefulness value `useful`, `partly_useful`, or `not_useful`, optional reason code, and optional free text capped at 1,000 characters. Do not require identity; issue an anonymous session token and apply rate limiting.

- [ ] **Step 4: Run the complete Plan 3 verification suite**

Run:

```bash
cd apps/api
alembic upgrade head
python -m pytest -v
ruff check src tests
mypy src
cd ../web
pnpm vitest run
pnpm playwright test tests/e2e/public-search.spec.ts tests/e2e/public-details.spec.ts
pnpm lint
pnpm typecheck
```

Expected: all checks pass; unsupported citations fail closed; the UI shows limitations and source links; anonymous feedback is stored without exposing internal identifiers.

- [ ] **Step 5: Commit the public discovery slice**

```bash
git add apps/api apps/web
git commit -m "feat: add grounded answers and usefulness feedback"
```

## Plan 3 Completion Gate

- Visitors can describe, inspect, edit, and submit a problem without authentication.
- Results are hybrid, filtered, stable, and explainable.
- The two territorial universes remain separate throughout filters and details.
- Solution, evidence, barrier, competence, production, comparison, and territory views contain only public validated intelligence.
- Grounded answers fail closed when citations or validated evidence are insufficient.
- Public component, API, browser, lint, and type checks pass.

