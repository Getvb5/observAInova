# ObservAInova Private Production Launch Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a private, operational ObservAInova pilot that starts with a public problem and returns only human-validated scientific contributions grounded in UFPE theses and dissertations from 2016–2025.

**Architecture:** Preserve the approved Next.js frontend, FastAPI API, PostgreSQL/pgvector canonical database, Redis queues, object storage, worker, and publication relay. Deploy the containerized services to Railway, keep the public problem drafts and candidate AI claims private by contract, and expose metadata before validation while exposing semantic intelligence only after curator and independent supervisor approval.

**Tech Stack:** Next.js 15, React 19, FastAPI, PostgreSQL 17 + pgvector, Redis 7, S3-compatible object storage, Dramatiq, Alembic, OIDC, Railway.

**Spec:** `docs/superpowers/specs/2026-09-21-problem-centered-innovation-ecosystem-design.md` and `docs/superpowers/specs/2026-09-23-scientific-contribution-governance-design.md`

## Global Constraints

- Corpus: theses and dissertations from public institutions headquartered in Pernambuco.
- Pilot source: UFPE institutional repository; IFPE remains the next approved source.
- Analytical period: 2016–2025; 2026 is a separate current layer.
- All knowledge areas remain eligible.
- Metadata may be visible before review; AI-derived intelligence must remain private until full human validation.
- Curator and supervisor must be different people for the same contribution version.
- The visitor journey starts with `Qual problema público você precisa enfrentar?`, never with a catalog.
- Every public scientific statement must retain source, location, provenance, version, and validation decision.
- Initial deployment remains private and must not broaden the audience without explicit approval.

## Review Focus

- A problem with no validated match must show an explicit evidence gap, never fabricate a solution.
- A source under maintenance must resume harvesting without duplicating raw or canonical records.
- A candidate AI claim must never appear in a public response before supervisor publication.
- A private deployment must reject unauthenticated visitors at the hosting boundary.
- A production rollback must preserve immutable source, validation, and publication history.

---

### Task 1: Freeze and publish the verified source state

**Files:**
- Create: `docs/superpowers/plans/2026-10-18-private-production-launch.md`

- [ ] Run the full local verification suite and record any environment-only exclusions.
- [ ] Commit this launch plan on `design/problem-centered-ecosystem`.
- [ ] Push the exact verified branch to `origin`.
- [ ] Confirm the remote head SHA equals the local head SHA.

### Task 2: Complete the problem-to-evidence public vertical slice

**Files:**
- Modify: `apps/api/src/pci/problems/router.py`
- Modify: `apps/api/src/pci/problems/service.py`
- Create: `apps/api/src/pci/problems/matching.py`
- Modify: `apps/web/src/components/problem/ProblemHandoff.tsx`
- Create: `apps/web/src/components/problem/ProblemEvidenceMap.tsx`
- Test: `apps/api/tests/problems/`
- Test: `apps/web/src/components/problem/`

- [ ] Add a failing API test proving confirmed problems retrieve published contributions only.
- [ ] Implement explainable matching against the public projection with explicit zero-evidence behavior.
- [ ] Add a failing component test for the confirmed problem evidence map.
- [ ] Replace the placeholder handoff with grounded results, citations, barriers, applicability, and gaps.
- [ ] Run backend, frontend, type, and build verification; commit the vertical slice.

### Task 3: Package production services

**Files:**
- Create: `apps/api/Dockerfile`
- Create: `apps/web/Dockerfile`
- Create: `infra/railway/README.md`
- Create: `infra/railway/api.toml`
- Create: `infra/railway/web.toml`
- Create: `infra/railway/worker.toml`
- Create: `infra/railway/publication-relay.toml`
- Modify: `.env.example`

- [ ] Add production container checks that fail before packaging exists.
- [ ] Package API, web, worker, and publication relay from immutable dependencies.
- [ ] Document required PostgreSQL, pgvector, Redis, object storage, OIDC, source, and AI-provider variables without committing secrets.
- [ ] Verify images build and health checks start; commit deployment packaging.

### Task 4: Provision the private Railway environment

- [ ] Create the Railway project from the GitHub repository after the Railway connection is confirmed.
- [ ] Provision PostgreSQL/pgvector, Redis, persistent object storage, API, worker, relay, and web services.
- [ ] Generate and store secrets only in the provider secret store.
- [ ] Configure private access, TLS, CORS, service health checks, and restart policies.
- [ ] Record provider-generated service identifiers without recording credentials.

### Task 5: Initialize the canonical database

- [ ] Run `alembic upgrade head` through revision `0019_return_correction_workflow`.
- [ ] Verify pgvector, constraints, publication guards, and append-only protections.
- [ ] Run an isolated backup/restore smoke test before loading the corpus.

### Task 6: Configure and harvest the UFPE pilot corpus

- [ ] Verify the official UFPE OAI-PMH endpoint and rights policy.
- [ ] Register UFPE with `institution_sector=public`, `institution_state=PE`, `corpus_types=[thesis, dissertation]`, `analysis_year_start=2016`, and `analysis_year_end=2025`.
- [ ] Run the initial resumable harvest and preserve raw provenance.
- [ ] Confirm deduplication, year/type eligibility, counts, failures, and source availability.

### Task 7: Produce and govern scientific intelligence

- [ ] Configure the approved AI extraction provider and schema/prompt versions in the secret store.
- [ ] Extract private candidate contributions with source spans and confidence.
- [ ] Generate the stratified and representative central-team review queue.
- [ ] Verify that no candidate appears in public APIs before curator and independent supervisor approval.
- [ ] Publish only the approved pilot contributions and rebuild the public semantic projection.

### Task 8: Deploy and verify the private pilot

- [ ] Deploy the exact verified Git commit.
- [ ] Run health, migration, authorization, publication-gate, and end-to-end smoke checks.
- [ ] Test the full journey: problem formulation → confirmation → validated contributions → source evidence.
- [ ] Verify explicit empty states for problems without validated evidence.
- [ ] Confirm the deployment audience is private and return the literal private URL.

## Execution Rulings

- Work continues on the existing non-main branch because the user explicitly authorized execution and the branch already contains the complete reviewed implementation history.
- Railway is the preferred production target because the approved architecture requires multiple containers, PostgreSQL/pgvector, Redis, persistent storage, workers, and TLS; the existing static Sites publication cannot run the Python/SQL stack as-is.
- If the UFPE repository is temporarily unavailable, harvesting must pause and resume from its saved cursor; no fabricated corpus or substituted institution is permitted.
