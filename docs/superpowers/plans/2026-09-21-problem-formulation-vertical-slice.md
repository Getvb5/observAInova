# Problem Formulation Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first working ObservAInova journey in which a person describes a public problem, answers guided contextual questions, reviews a faithful structured formulation, confirms an immutable version, and reaches a safe handoff to the future solution-map service.

**Architecture:** Add a private-by-default problem aggregate to the existing FastAPI/PostgreSQL application. Answers are append-only events, confirmed contexts are immutable versions, and a deterministic dialogue engine asks one explicit question at a time without a live AI dependency or invented interpretation. A new Next.js public application makes this problem-first flow the homepage and stores the one-time edit token only in the browser session.

**Tech Stack:** Python 3.12, FastAPI 0.115, SQLAlchemy 2, Alembic, PostgreSQL 17, Pydantic 2, pytest, Next.js 15, React 19, TypeScript, Vitest, Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-problem-centered-innovation-ecosystem-design.md`

## Global Constraints

- The homepage copy is exactly `Qual problema público você precisa enfrentar?`; the productions catalog remains a secondary API and is not linked as the primary journey.
- This subproject ends at a confirmed problem and an explicit `awaiting_validated_contributions` handoff; it does not fabricate a solution map before the validated-contribution subsystem exists.
- Problems are private by default. Every read or mutation requires the raw edit token returned once at creation; only its SHA-256 digest is persisted.
- Unknown answers are valid. The dialogue must store `unknown` and leave the corresponding value absent instead of generating an answer.
- The original description and every supplied value are preserved verbatim after trimming surrounding whitespace; the system may arrange them into a labeled summary but may not paraphrase them.
- `perceived_causes` is always classified as `perception` or `unknown`; no endpoint may promote it to a verified fact.
- Answer events and confirmed context versions are append-only; corrections create new events and reconfirmation creates a new version.
- Unauthorized and nonexistent problem identifiers return the same `404 {"detail": "Problem not found"}` response.
- Public API schemas use `extra="forbid"`; free-text fields are bounded to 5,000 Unicode characters and reject blank-only values.
- The flow has no dependency on a live language-model provider, embeddings, validated contributions, or an external identity provider.
- Existing ingestion, normalization, storage, production, and public-projection behavior must remain unchanged; the current baseline is 137 passing API tests, clean Ruff, and clean strict mypy.
- All user-facing copy is Brazilian Portuguese and all interactive controls are keyboard operable with visible focus.

## Review Focus

1. Blank, whitespace-only, and over-5,000-character descriptions or answers must return 422 without creating or mutating a problem; Task 4 pins this through API boundary tests.
2. `unknown` must satisfy a dialogue slot without generating replacement text, and confirmed JSON must preserve `null`; Task 3 pins this in pure engine tests and Task 4 at the API boundary.
3. Correcting an earlier answer must preserve the first event while exposing the newest value in the draft and next confirmed version; Task 2 pins event history and Task 4 pins reconfirmation.
4. A wrong token must be indistinguishable from a random problem UUID and raw tokens must never appear in persisted rows, logs, or response bodies after creation; Task 2 pins storage and comparison, Task 4 pins HTTP behavior.
5. Confirmation with unaddressed slots must return a deterministic missing-field list and never create a partial context version; Task 3 pins field order and Task 4 pins transaction behavior.

---

## Repository Map for This Subproject

```text
apps/api/
  alembic/versions/0010_public_problem_formulation.py
  src/pci/problems/
    __init__.py
    dialogue.py
    models.py
    repository.py
    router.py
    schemas.py
    security.py
    service.py
  tests/problems/
    test_dialogue.py
    test_models.py
    test_repository.py
    test_service.py
  tests/api/test_problem_api.py
  tests/migrations/test_problem_migration.py
apps/web/
  package.json
  package-lock.json
  next.config.ts
  tsconfig.json
  vitest.config.ts
  playwright.config.ts
  src/app/globals.css
  src/app/layout.tsx
  src/app/page.tsx
  src/components/problem/ProblemAssistant.tsx
  src/components/problem/ProblemReview.tsx
  src/components/problem/ProblemHandoff.tsx
  src/lib/problem-api.ts
  src/test/setup.ts
  src/components/problem/ProblemAssistant.test.tsx
  e2e/problem-formulation.spec.ts
docs/development/problem-formulation-flow.md
```

### Task 1: Persist problem aggregates, answer events, and confirmed versions

**Files:**
- Create: `apps/api/src/pci/problems/__init__.py`
- Create: `apps/api/src/pci/problems/models.py`
- Create: `apps/api/alembic/versions/0010_public_problem_formulation.py`
- Modify: `apps/api/src/pci/models/__init__.py`
- Create: `apps/api/tests/problems/test_models.py`
- Create: `apps/api/tests/migrations/test_problem_migration.py`

**Interfaces:**
- Produces: `ProblemStatus`, `ProblemVisibility`, `ProblemField`, and `KnowledgeStatus` string enums.
- Produces: `PublicProblem`, `ProblemAnswerEvent`, and `ProblemContextVersion` SQLAlchemy models.
- Produces database tables `public_problems`, `problem_answer_events`, and `problem_context_versions` in revision `0010_public_problem_formulation`, down-revision `0009_storage_attempt_lease`.

- [ ] **Step 1: Write failing enum, immutability, and uniqueness tests**

Create `apps/api/tests/problems/test_models.py` with these focused cases:

```python
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pci.problems.models import (
    KnowledgeStatus,
    ProblemAnswerEvent,
    ProblemContextVersion,
    ProblemField,
    PublicProblem,
)


def test_problem_field_values_are_stable() -> None:
    assert [item.value for item in ProblemField] == [
        "territory",
        "affected_population_or_service",
        "observed_consequences",
        "perceived_causes",
        "attempted_actions",
        "available_resources",
        "constraints",
        "desired_outcome",
    ]


def test_answer_event_is_append_only(session: Session) -> None:
    problem = PublicProblem(description="Demora no atendimento", edit_token_digest="a" * 64)
    session.add(problem)
    session.flush()
    event = ProblemAnswerEvent(
        problem_id=problem.id,
        sequence=1,
        field=ProblemField.TERRITORY,
        value="Caruaru",
        knowledge_status=KnowledgeStatus.REPORTED_FACT,
    )
    session.add(event)
    session.commit()
    event.value = "Recife"
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()


def test_context_version_is_unique_per_problem_and_number(session: Session) -> None:
    problem = PublicProblem(description="Demora no atendimento", edit_token_digest="b" * 64)
    session.add(problem)
    session.flush()
    context = {"territory": {"value": None, "knowledge_status": "unknown"}}
    session.add_all(
        [
            ProblemContextVersion(
                problem_id=problem.id, version=1, structured_summary="Resumo", context=context
            ),
            ProblemContextVersion(
                problem_id=problem.id, version=1, structured_summary="Outro", context=context
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run the new model tests and confirm the expected import failure**

Run:

```bash
cd apps/api
uv run python -m pytest tests/problems/test_models.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'pci.problems'`.

- [ ] **Step 3: Implement enums and SQLAlchemy models**

Create the enums and model surface in `apps/api/src/pci/problems/models.py`:

```python
class ProblemStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class ProblemVisibility(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"
    PUBLIC = "public"


class ProblemField(StrEnum):
    TERRITORY = "territory"
    AFFECTED_POPULATION_OR_SERVICE = "affected_population_or_service"
    OBSERVED_CONSEQUENCES = "observed_consequences"
    PERCEIVED_CAUSES = "perceived_causes"
    ATTEMPTED_ACTIONS = "attempted_actions"
    AVAILABLE_RESOURCES = "available_resources"
    CONSTRAINTS = "constraints"
    DESIRED_OUTCOME = "desired_outcome"


class KnowledgeStatus(StrEnum):
    REPORTED_FACT = "reported_fact"
    PERCEPTION = "perception"
    UNKNOWN = "unknown"


```

Implement the following columns exactly:

```python
class PublicProblem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "public_problems"

    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ProblemStatus] = mapped_column(problem_status_type, default=ProblemStatus.DRAFT)
    visibility: Mapped[ProblemVisibility] = mapped_column(
        problem_visibility_type, default=ProblemVisibility.PRIVATE
    )
    edit_token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    answer_events: Mapped[list["ProblemAnswerEvent"]] = relationship(
        back_populates="problem", passive_deletes="all"
    )
    context_versions: Mapped[list["ProblemContextVersion"]] = relationship(
        back_populates="problem", passive_deletes="all"
    )


class ProblemAnswerEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "problem_answer_events"
    __table_args__ = (
        UniqueConstraint("problem_id", "sequence", name="uq_problem_answer_sequence"),
    )

    problem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_problems.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    field: Mapped[ProblemField] = mapped_column(problem_field_type, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    knowledge_status: Mapped[KnowledgeStatus] = mapped_column(
        knowledge_status_type, nullable=False
    )
    problem: Mapped[PublicProblem] = relationship(back_populates="answer_events")


class ProblemContextVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "problem_context_versions"
    __table_args__ = (
        UniqueConstraint("problem_id", "version", name="uq_problem_context_version"),
    )

    problem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_problems.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    structured_summary: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    problem: Mapped[PublicProblem] = relationship(back_populates="context_versions")
```

Use named SQLAlchemy enums with `values_callable=enum_values`, `validate_strings=True`, and `create_constraint=True`. Register `before_update` and `before_delete` listeners using `reject_append_only_change` for both append-only models. Export all three models from `pci.models` so `Base.metadata.create_all()` sees them during tests.

- [ ] **Step 4: Add reversible Alembic revision 0010 and its migration test**

The upgrade creates named enum types and the three tables, including indexes on `status`, `field`, `problem_id`, and `confirmed_at`. The downgrade drops tables in reverse dependency order and then drops the enum types.

Create `apps/api/tests/migrations/test_problem_migration.py`:

```python
from alembic import command
from alembic.config import Config


def test_problem_migration_contains_private_versioned_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)
    ddl = " ".join(capsys.readouterr().out.split())
    assert "CREATE TABLE public_problems" in ddl
    assert "CREATE TABLE problem_answer_events" in ddl
    assert "CREATE TABLE problem_context_versions" in ddl
    assert "edit_token_digest VARCHAR(64) NOT NULL" in ddl
    assert "UNIQUE (problem_id, sequence)" in ddl
    assert "UNIQUE (problem_id, version)" in ddl
```

- [ ] **Step 5: Run focused and full backend checks**

Run:

```bash
cd apps/api
uv run python -m pytest tests/problems/test_models.py tests/migrations/test_problem_migration.py -v
uv run python -m pytest
uv run ruff check src tests
uv run mypy src
```

Expected: all focused tests and the original 137 tests pass; Ruff and mypy report no issues.

- [ ] **Step 6: Commit the domain schema**

```bash
git add apps/api/src/pci/problems apps/api/src/pci/models/__init__.py \
  apps/api/alembic/versions/0010_public_problem_formulation.py \
  apps/api/tests/problems apps/api/tests/migrations/test_problem_migration.py
git commit -m "feat: add versioned public problem domain"
```

### Task 2: Secure private access and append answers without losing history

**Files:**
- Create: `apps/api/src/pci/problems/security.py`
- Create: `apps/api/src/pci/problems/repository.py`
- Create: `apps/api/tests/problems/test_repository.py`

**Interfaces:**
- Produces: `generate_edit_token() -> str`.
- Produces: `digest_edit_token(token: str) -> str` and `token_matches(token: str, digest: str) -> bool`.
- Produces: `create_problem(session: Session, description: str) -> tuple[PublicProblem, str]`.
- Produces: `get_authorized_problem(session: Session, problem_id: UUID, token: str) -> PublicProblem | None`.
- Produces: `append_answer(session: Session, problem: PublicProblem, field: ProblemField, value: str | None, knowledge_status: KnowledgeStatus) -> ProblemAnswerEvent`.
- Produces: `latest_answers(session: Session, problem_id: UUID) -> dict[ProblemField, ProblemAnswerEvent]`.
- Produces: `list_answer_events(session: Session, problem_id: UUID) -> tuple[ProblemAnswerEvent, ...]`.

- [ ] **Step 1: Write failing token, history, and correction tests**

Create `apps/api/tests/problems/test_repository.py`:

```python
def test_create_problem_returns_token_but_stores_only_digest(session: Session) -> None:
    problem, token = create_problem(session, "A fila para consultas está aumentando")
    session.flush()
    assert len(token) >= 43
    assert problem.edit_token_digest == digest_edit_token(token)
    assert token not in str(problem.__dict__)


def test_wrong_token_and_unknown_id_are_both_unauthorized(session: Session) -> None:
    problem, token = create_problem(session, "A fila para consultas está aumentando")
    session.flush()
    assert get_authorized_problem(session, problem.id, token) is problem
    assert get_authorized_problem(session, problem.id, "wrong") is None
    assert get_authorized_problem(session, uuid.uuid4(), token) is None


def test_correction_preserves_history_and_latest_answer_wins(session: Session) -> None:
    problem, _ = create_problem(session, "A fila para consultas está aumentando")
    append_answer(
        session,
        problem,
        ProblemField.TERRITORY,
        "Recife",
        KnowledgeStatus.REPORTED_FACT,
    )
    append_answer(
        session,
        problem,
        ProblemField.TERRITORY,
        "Caruaru",
        KnowledgeStatus.REPORTED_FACT,
    )
    session.flush()
    assert [event.value for event in list_answer_events(session, problem.id)] == [
        "Recife",
        "Caruaru",
    ]
    assert latest_answers(session, problem.id)[ProblemField.TERRITORY].value == "Caruaru"
```

- [ ] **Step 2: Run repository tests and verify missing functions**

Run: `cd apps/api && uv run python -m pytest tests/problems/test_repository.py -v`

Expected: FAIL because `security.py` and `repository.py` do not exist.

- [ ] **Step 3: Implement token generation and constant-time verification**

Create `security.py` with no logging:

```python
import hashlib
import hmac
import secrets


def generate_edit_token() -> str:
    return secrets.token_urlsafe(32)


def digest_edit_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str, digest: str) -> bool:
    return hmac.compare_digest(digest_edit_token(token), digest)
```

- [ ] **Step 4: Implement repository transactions and latest-value projection**

`create_problem()` trims the description, creates the raw token, stores only its digest, adds the problem, and returns `(problem, raw_token)` without committing.

`append_answer()` locks the problem row with `select(PublicProblem).where(...).with_for_update()`, consumes `next_event_sequence`, increments it, adds the event, and flushes. `latest_answers()` orders by ascending sequence and replaces the projected value for a field while leaving all events intact.

The authorization query must fetch by UUID first and call `token_matches()` only when a row exists:

```python
def get_authorized_problem(
    session: Session, problem_id: uuid.UUID, token: str
) -> PublicProblem | None:
    problem = session.get(PublicProblem, problem_id)
    if problem is None or not token_matches(token, problem.edit_token_digest):
        return None
    return problem
```

- [ ] **Step 5: Verify focused and regression tests**

Run:

```bash
cd apps/api
uv run python -m pytest tests/problems/test_repository.py -v
uv run python -m pytest tests/problems tests/api tests/models -v
uv run ruff check src tests
uv run mypy src
```

Expected: repository tests pass, previous API/model tests remain green, and static checks pass.

- [ ] **Step 6: Commit private access and event history**

```bash
git add apps/api/src/pci/problems apps/api/tests/problems/test_repository.py
git commit -m "feat: secure problem drafts and preserve answer history"
```

### Task 3: Implement the deterministic, non-hallucinating dialogue engine

**Files:**
- Create: `apps/api/src/pci/problems/dialogue.py`
- Create: `apps/api/tests/problems/test_dialogue.py`

**Interfaces:**
- Produces: `FIELD_ORDER: tuple[ProblemField, ...]`.
- Produces: `FieldAnswer(value: str | None, knowledge_status: KnowledgeStatus)` frozen dataclass.
- Produces: `ProblemDraft(description: str, answers: Mapping[ProblemField, FieldAnswer])` frozen dataclass.
- Produces: `NextQuestion(field: ProblemField, prompt: str, accepts_unknown: bool = True)` frozen dataclass.
- Produces: `build_draft(description: str, events: Iterable[ProblemAnswerEvent]) -> ProblemDraft`.
- Produces: `get_next_question(draft: ProblemDraft) -> NextQuestion | None`.
- Produces: `missing_fields(draft: ProblemDraft) -> tuple[ProblemField, ...]`.
- Produces: `validate_answer(field: ProblemField, value: str | None, knowledge_status: KnowledgeStatus) -> FieldAnswer`.
- Produces: `build_context(draft: ProblemDraft) -> dict[str, object]` and `build_summary(draft: ProblemDraft) -> str`.
- Produces: `IncompleteProblemError.missing_fields: tuple[ProblemField, ...]`.

- [ ] **Step 1: Write failing dialogue tests for order, unknowns, classifications, and summary fidelity**

```python
def complete_draft(**overrides: str) -> ProblemDraft:
    values = {
        ProblemField.TERRITORY: overrides.get("territory", "Caruaru"),
        ProblemField.AFFECTED_POPULATION_OR_SERVICE: overrides.get(
            "population", "adultos aguardando cardiologia"
        ),
        ProblemField.OBSERVED_CONSEQUENCES: overrides.get(
            "consequence", "espera superior a 90 dias"
        ),
        ProblemField.PERCEIVED_CAUSES: overrides.get(
            "cause", "oferta insuficiente, segundo a equipe"
        ),
        ProblemField.ATTEMPTED_ACTIONS: "remanejamento manual de vagas",
        ProblemField.AVAILABLE_RESOURCES: "equipe de regulação e dados de agenda",
        ProblemField.CONSTRAINTS: "sem aumento de equipe",
        ProblemField.DESIRED_OUTCOME: overrides.get(
            "desired", "reduzir a espera preservando equidade"
        ),
    }
    answers = {
        field: FieldAnswer(
            value=value,
            knowledge_status=(
                KnowledgeStatus.PERCEPTION
                if field is ProblemField.PERCEIVED_CAUSES
                else KnowledgeStatus.REPORTED_FACT
            ),
        )
        for field, value in values.items()
    }
    return ProblemDraft(description="Demora no atendimento", answers=answers)


def test_dialogue_asks_fields_in_fixed_order() -> None:
    draft = ProblemDraft(description="Demora no atendimento", answers={})
    assert get_next_question(draft).field is ProblemField.TERRITORY
    assert missing_fields(draft) == FIELD_ORDER


def test_unknown_is_complete_without_invented_value() -> None:
    answer = validate_answer(
        ProblemField.ATTEMPTED_ACTIONS,
        None,
        KnowledgeStatus.UNKNOWN,
    )
    draft = ProblemDraft(
        description="Demora no atendimento",
        answers={ProblemField.ATTEMPTED_ACTIONS: answer},
    )
    assert draft.answers[ProblemField.ATTEMPTED_ACTIONS].value is None
    assert ProblemField.ATTEMPTED_ACTIONS not in missing_fields(draft)


def test_perceived_cause_cannot_be_classified_as_fact() -> None:
    with pytest.raises(ValueError, match="perception or unknown"):
        validate_answer(
            ProblemField.PERCEIVED_CAUSES,
            "Falta de profissionais",
            KnowledgeStatus.REPORTED_FACT,
        )


def test_summary_uses_exact_supplied_phrases() -> None:
    draft = complete_draft(
        territory="Caruaru",
        population="adultos aguardando cardiologia",
        consequence="espera superior a 90 dias",
        cause="oferta insuficiente, segundo a equipe",
        desired="reduzir a espera preservando equidade",
    )
    summary = build_summary(draft)
    for phrase in [
        "Caruaru",
        "adultos aguardando cardiologia",
        "espera superior a 90 dias",
        "oferta insuficiente, segundo a equipe",
        "reduzir a espera preservando equidade",
    ]:
        assert phrase in summary
```

- [ ] **Step 2: Run dialogue tests and verify failure**

Run: `cd apps/api && uv run python -m pytest tests/problems/test_dialogue.py -v`

Expected: FAIL because the dialogue engine does not exist.

- [ ] **Step 3: Implement field order and exact Portuguese prompts**

Use this fixed order and prompt mapping:

```python
FIELD_ORDER = (
    ProblemField.TERRITORY,
    ProblemField.AFFECTED_POPULATION_OR_SERVICE,
    ProblemField.OBSERVED_CONSEQUENCES,
    ProblemField.PERCEIVED_CAUSES,
    ProblemField.ATTEMPTED_ACTIONS,
    ProblemField.AVAILABLE_RESOURCES,
    ProblemField.CONSTRAINTS,
    ProblemField.DESIRED_OUTCOME,
)

PROMPTS = {
    ProblemField.TERRITORY: "Em qual território ou unidade administrativa isso acontece?",
    ProblemField.AFFECTED_POPULATION_OR_SERVICE: (
        "Qual população, serviço ou organização é mais afetado?"
    ),
    ProblemField.OBSERVED_CONSEQUENCES: "Quais consequências você observa?",
    ProblemField.PERCEIVED_CAUSES: (
        "Quais causas são percebidas? Elas serão registradas como percepções, não como fatos comprovados."
    ),
    ProblemField.ATTEMPTED_ACTIONS: "O que já foi tentado e qual foi o resultado?",
    ProblemField.AVAILABLE_RESOURCES: "Quais recursos ou capacidades já estão disponíveis?",
    ProblemField.CONSTRAINTS: "Quais restrições precisam ser respeitadas?",
    ProblemField.DESIRED_OUTCOME: "Que resultado concreto você deseja alcançar?",
}
```

`get_next_question()` returns the first unanswered field. An `unknown` answer counts as answered. `validate_answer()` trims non-null text, rejects blank or over-5,000-character values, requires null when status is `unknown`, requires a value otherwise, and limits `perceived_causes` to `perception` or `unknown`.

- [ ] **Step 4: Implement faithful context JSON and structured summary**

`build_context()` returns every field, including unknowns:

```python
{
    "description": draft.description,
    "territory": {"value": "Caruaru", "knowledge_status": "reported_fact"},
    "perceived_causes": {
        "value": "oferta insuficiente, segundo a equipe",
        "knowledge_status": "perception",
    },
    "attempted_actions": {"value": None, "knowledge_status": "unknown"},
}
```

`build_summary()` uses fixed labels and exact values. For unknown fields it writes `não informado`; for causes it uses the label `Causas percebidas`. It raises `IncompleteProblemError(missing_fields)` when any field has not been addressed.

- [ ] **Step 5: Verify pure engine tests and type safety**

Run:

```bash
cd apps/api
uv run python -m pytest tests/problems/test_dialogue.py -v
uv run ruff check src tests
uv run mypy src
```

Expected: all dialogue tests pass; the engine has no database, HTTP, or external-provider dependency.

- [ ] **Step 6: Commit the dialogue engine**

```bash
git add apps/api/src/pci/problems/dialogue.py apps/api/tests/problems/test_dialogue.py
git commit -m "feat: guide faithful public problem formulation"
```

### Task 4: Expose creation, answering, confirmation, and revision APIs

**Files:**
- Create: `apps/api/src/pci/problems/schemas.py`
- Create: `apps/api/src/pci/problems/service.py`
- Create: `apps/api/src/pci/problems/router.py`
- Modify: `apps/api/src/pci/main.py`
- Modify: `.env.example`
- Create: `apps/api/tests/problems/test_service.py`
- Create: `apps/api/tests/api/test_problem_api.py`

**Interfaces:**
- Produces: `POST /api/v1/problems`.
- Produces: `GET /api/v1/problems/{problem_id}`.
- Produces: `POST /api/v1/problems/{problem_id}/answers`.
- Produces: `POST /api/v1/problems/{problem_id}/confirm`.
- Produces: `POST /api/v1/problems/{problem_id}/revisions`.
- Consumes raw token from `X-Problem-Token` for every endpoint except creation.
- Produces response state `draft`, `confirmed`, `next_question`, `missing_fields`, `ready_to_confirm`, `current_version`, and `map_status`.
- Produces service dataclasses `CreatedProblem(problem: PublicProblem, edit_token: str)`, `ProblemState`, and `Confirmation(problem: PublicProblem, version: ProblemContextVersion, map_status: Literal["awaiting_validated_contributions"])`.
- Produces `ProblemStateConflict(code: str)` for invalid transitions.

- [ ] **Step 1: Write failing service transaction tests**

Create `apps/api/tests/problems/test_service.py`:

```python
def answer_all_fields(
    session: Session, problem: PublicProblem, *, unknown_optional: bool
) -> None:
    for field in FIELD_ORDER:
        if unknown_optional and field not in {
            ProblemField.AFFECTED_POPULATION_OR_SERVICE,
            ProblemField.DESIRED_OUTCOME,
        }:
            record_answer(session, problem, field, None, KnowledgeStatus.UNKNOWN)
            continue
        status = (
            KnowledgeStatus.PERCEPTION
            if field is ProblemField.PERCEIVED_CAUSES
            else KnowledgeStatus.REPORTED_FACT
        )
        record_answer(session, problem, field, f"resposta para {field.value}", status)


def create_and_confirm_complete_problem(session: Session) -> CreatedProblem:
    created = create_public_problem(session, "A fila para consultas está aumentando")
    answer_all_fields(session, created.problem, unknown_optional=False)
    confirm_public_problem(session, created.problem)
    return created


def test_confirm_creates_immutable_version_and_updates_problem(session: Session) -> None:
    created = create_public_problem(session, "A fila para consultas está aumentando")
    answer_all_fields(session, created.problem, unknown_optional=True)
    result = confirm_public_problem(session, created.problem)
    assert result.version.version == 1
    assert result.problem.status is ProblemStatus.CONFIRMED
    assert result.problem.current_version_number == 1
    assert result.map_status == "awaiting_validated_contributions"


def test_incomplete_confirmation_does_not_create_version(session: Session) -> None:
    created = create_public_problem(session, "A fila para consultas está aumentando")
    with pytest.raises(IncompleteProblemError) as error:
        confirm_public_problem(session, created.problem)
    assert error.value.missing_fields == FIELD_ORDER
    assert session.query(ProblemContextVersion).count() == 0


def test_revision_reuses_latest_answers_and_creates_version_two(session: Session) -> None:
    created = create_and_confirm_complete_problem(session)
    reopen_problem(session, created.problem)
    record_answer(
        session,
        created.problem,
        ProblemField.CONSTRAINTS,
        "Sem aumento de equipe",
        KnowledgeStatus.REPORTED_FACT,
    )
    result = confirm_public_problem(session, created.problem)
    assert result.version.version == 2
    assert result.version.context["constraints"]["value"] == "Sem aumento de equipe"
```

- [ ] **Step 2: Write failing HTTP boundary and privacy tests**

Create `apps/api/tests/api/test_problem_api.py` with at least these tests:

```python
def complete_api_answers() -> list[tuple[str, str, str]]:
    return [
        ("territory", "Caruaru", "reported_fact"),
        (
            "affected_population_or_service",
            "adultos aguardando cardiologia",
            "reported_fact",
        ),
        ("observed_consequences", "espera superior a 90 dias", "reported_fact"),
        ("perceived_causes", "oferta insuficiente, segundo a equipe", "perception"),
        ("attempted_actions", "remanejamento manual de vagas", "reported_fact"),
        (
            "available_resources",
            "equipe de regulação e dados de agenda",
            "reported_fact",
        ),
        ("constraints", "sem aumento de equipe", "reported_fact"),
        ("desired_outcome", "reduzir a espera preservando equidade", "reported_fact"),
    ]


def test_problem_flow_from_description_to_confirmation(client: TestClient) -> None:
    created = client.post(
        "/api/v1/problems",
        json={"description": "As pessoas aguardam muito por consultas especializadas"},
    )
    assert created.status_code == 201
    problem_id = created.json()["problem_id"]
    token = created.json()["edit_token"]
    state = created.json()["state"]
    assert state["next_question"]["field"] == "territory"

    headers = {"X-Problem-Token": token}
    answers = complete_api_answers()
    for field, value, knowledge_status in answers:
        response = client.post(
            f"/api/v1/problems/{problem_id}/answers",
            headers=headers,
            json={"field": field, "value": value, "knowledge_status": knowledge_status},
        )
        assert response.status_code == 200

    confirmed = client.post(f"/api/v1/problems/{problem_id}/confirm", headers=headers)
    assert confirmed.status_code == 201
    assert confirmed.json()["current_version"] == 1
    assert confirmed.json()["map_status"] == "awaiting_validated_contributions"
    assert "edit_token" not in confirmed.json()


@pytest.mark.parametrize("description", ["", "   ", "x" * 5001])
def test_invalid_description_never_creates_problem(
    client: TestClient, session: Session, description: str
) -> None:
    response = client.post("/api/v1/problems", json={"description": description})
    assert response.status_code == 422
    assert session.query(PublicProblem).count() == 0


def test_wrong_token_and_unknown_problem_are_indistinguishable(client: TestClient) -> None:
    created = client.post("/api/v1/problems", json={"description": "Problema válido"})
    problem_id = created.json()["problem_id"]
    wrong = client.get(
        f"/api/v1/problems/{problem_id}", headers={"X-Problem-Token": "wrong"}
    )
    unknown = client.get(
        f"/api/v1/problems/{uuid.uuid4()}",
        headers={"X-Problem-Token": created.json()["edit_token"]},
    )
    assert wrong.status_code == unknown.status_code == 404
    assert wrong.json() == unknown.json() == {"detail": "Problem not found"}
```

Also test: blank/oversized answers return 422 without adding an event; `unknown` accepts null and returns no invented value; confirming early returns 409 with the ordered missing fields; answering a confirmed problem returns 409 until revisions is called; a correction followed by reconfirmation creates version 2 while version 1 is unchanged; `extra` request keys return 422.

- [ ] **Step 3: Implement strict request and response schemas**

Use a shared base:

```python
class ProblemSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProblemRequest(ProblemSchema):
    description: str = Field(min_length=1, max_length=5000)

    @field_validator("description")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("description must not be blank")
        return value


class AnswerProblemRequest(ProblemSchema):
    field: ProblemField
    value: str | None = Field(default=None, max_length=5000)
    knowledge_status: KnowledgeStatus
```

Define explicit `NextQuestionResponse`, `ProblemFieldResponse`, `ProblemStateResponse`, `CreatedProblemResponse`, and `ConfirmedProblemResponse`. `CreatedProblemResponse` is the only schema containing `edit_token`. `ConfirmedProblemResponse.map_status` is `Literal["awaiting_validated_contributions"]`.

The state contract is fixed as:

```python
class NextQuestionResponse(ProblemSchema):
    field: ProblemField
    prompt: str
    accepts_unknown: bool


class ProblemFieldResponse(ProblemSchema):
    value: str | None
    knowledge_status: KnowledgeStatus


class ProblemStateResponse(ProblemSchema):
    problem_id: uuid.UUID
    status: ProblemStatus
    description: str
    fields: dict[ProblemField, ProblemFieldResponse | None]
    next_question: NextQuestionResponse | None
    missing_fields: list[ProblemField]
    ready_to_confirm: bool
    current_version: int
    structured_summary: str | None
    map_status: Literal["not_ready", "awaiting_validated_contributions"]


class CreatedProblemResponse(ProblemSchema):
    problem_id: uuid.UUID
    edit_token: str
    state: ProblemStateResponse


class ConfirmedProblemResponse(ProblemStateResponse):
    map_status: Literal["awaiting_validated_contributions"]
```

- [ ] **Step 4: Implement application service and transaction rules**

The service owns state transitions:

```python
def record_answer(
    session: Session,
    problem: PublicProblem,
    field: ProblemField,
    value: str | None,
    knowledge_status: KnowledgeStatus,
) -> ProblemState:
    if problem.status is ProblemStatus.CONFIRMED:
        raise ProblemStateConflict("reopen_before_answering")
    answer = validate_answer(field, value, knowledge_status)
    append_answer(session, problem, field, answer.value, answer.knowledge_status)
    return get_problem_state(session, problem)


def confirm_public_problem(session: Session, problem: PublicProblem) -> Confirmation:
    draft = build_draft(problem.description, list_answer_events(session, problem.id))
    context = build_context(draft)
    summary = build_summary(draft)
    version_number = problem.current_version_number + 1
    version = ProblemContextVersion(
        problem_id=problem.id,
        version=version_number,
        context=context,
        structured_summary=summary,
    )
    session.add(version)
    problem.current_version_number = version_number
    problem.status = ProblemStatus.CONFIRMED
    session.flush()
    return Confirmation(
        problem=problem,
        version=version,
        map_status="awaiting_validated_contributions",
    )
```

`reopen_problem()` changes only `status` from `confirmed` to `draft`; historical answers and context versions remain untouched. An already-draft problem returns its current state idempotently.

- [ ] **Step 5: Add router, shared session dependency, title, and development CORS**

Move the duplicated request-session dependency from `productions/router.py` to `pci/api_dependencies.py` and import it in both routers. Include the problem router at `/api/v1`. Change the FastAPI title to `ObservAInova`.

Read `FRONTEND_ORIGINS` in `main.py` as a comma-separated list with the development default `http://localhost:3000`, discard blank entries, and install `CORSMiddleware` with the resulting exact origins, `allow_credentials=False`, methods `GET` and `POST`, and headers `Content-Type` and `X-Problem-Token`. Do not instantiate the existing required `Settings` object during `create_app()` and do not use wildcard origins. Add `FRONTEND_ORIGINS=http://localhost:3000` to `.env.example`.

Endpoint status behavior:

| Operation | Success | Invalid input | Wrong state | Unauthorized/unknown |
|---|---:|---:|---:|---:|
| Create | 201 | 422 | — | — |
| Read | 200 | 422 | — | 404 |
| Answer | 200 | 422 | 409 | 404 |
| Confirm | 201 | 422 | 409 | 404 |
| Reopen | 200 | 422 | — | 404 |

- [ ] **Step 6: Run API flow, regression, lint, and type checks**

Run:

```bash
cd apps/api
uv run python -m pytest tests/problems tests/api/test_problem_api.py -v
uv run python -m pytest
uv run ruff check src tests
uv run mypy src
```

Expected: the full problem flow passes, all original 137 tests remain green, and static checks pass.

- [ ] **Step 7: Commit the public-problem API**

```bash
git add .env.example apps/api/src/pci apps/api/tests
git commit -m "feat: expose private problem formulation API"
```

### Task 5: Make problem formulation the public homepage

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/package-lock.json`
- Create: `apps/web/next.config.ts`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/vitest.config.ts`
- Create: `apps/web/src/test/setup.ts`
- Create: `apps/web/src/app/globals.css`
- Create: `apps/web/src/app/layout.tsx`
- Create: `apps/web/src/app/page.tsx`
- Create: `apps/web/src/lib/problem-api.ts`
- Create: `apps/web/src/components/problem/ProblemAssistant.tsx`
- Create: `apps/web/src/components/problem/ProblemReview.tsx`
- Create: `apps/web/src/components/problem/ProblemHandoff.tsx`
- Create: `apps/web/src/components/problem/ProblemAssistant.test.tsx`

**Interfaces:**
- Consumes: problem API operations from Task 4.
- Produces: `ProblemApi` with `create`, `read`, `answer`, `confirm`, and `reopen` methods.
- Produces: `ProblemApiError(status: number, body: unknown)` without storing request headers.
- Produces: `/` as the problem-first public experience.
- Stores: `{problemId, editToken}` in `sessionStorage` key `observainova.problem-session.v1`; never places the token in a URL, HTML data attribute, analytics event, or console output.

- [ ] **Step 1: Scaffold Next.js 15 and lock dependencies**

Create `package.json` with scripts:

```json
{
  "name": "observainova-web",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@playwright/test": "^1.49.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^25.0.0",
    "typescript": "^5.7.0",
    "vite": "^5.4.0",
    "vitest": "^2.1.0"
  }
}
```

Run `cd apps/web && npm install` once to generate and commit `package-lock.json`. Configure the API base as `NEXT_PUBLIC_API_BASE_URL`, defaulting to `http://localhost:8000/api/v1` only in development.

- [ ] **Step 2: Write failing interaction tests before components**

Create `ProblemAssistant.test.tsx` using a fake `ProblemApi` injected as a prop:

```tsx
const emptyFields: ProblemState["fields"] = {
  territory: null,
  affected_population_or_service: null,
  observed_consequences: null,
  perceived_causes: null,
  attempted_actions: null,
  available_resources: null,
  constraints: null,
  desired_outcome: null,
};

function stateWithNextQuestion(field: ProblemField): ProblemState {
  return {
    problem_id: "00000000-0000-4000-8000-000000000001",
    status: "draft",
    description: "As pessoas aguardam muito por consultas especializadas",
    fields: { ...emptyFields },
    next_question: {
      field,
      prompt: "Em qual território ou unidade administrativa isso acontece?",
      accepts_unknown: true,
    },
    missing_fields: Object.keys(emptyFields) as ProblemField[],
    ready_to_confirm: false,
    current_version: 0,
    structured_summary: null,
    map_status: "not_ready",
  };
}

function completeProblemState(values: { constraints: string }): ProblemState {
  const fields = Object.fromEntries(
    (Object.keys(emptyFields) as ProblemField[]).map((field) => [
      field,
      {
        value: field === "constraints" ? values.constraints : `resposta para ${field}`,
        knowledge_status: field === "perceived_causes" ? "perception" : "reported_fact",
      },
    ]),
  ) as ProblemState["fields"];
  return {
    ...stateWithNextQuestion("territory"),
    fields,
    next_question: null,
    missing_fields: [],
    ready_to_confirm: true,
    structured_summary: "Formulação pronta para confirmação",
  };
}

function fakeApi(overrides: Partial<ProblemApi> = {}): ProblemApi {
  return {
    create: vi.fn(),
    read: vi.fn(),
    answer: vi.fn(),
    confirm: vi.fn(),
    reopen: vi.fn(),
    ...overrides,
  };
}

function fakeApiWithTerritoryQuestion(): ProblemApi {
  return fakeApi({
    read: vi.fn().mockResolvedValue(stateWithNextQuestion("territory")),
    answer: vi.fn().mockResolvedValue(
      stateWithNextQuestion("affected_population_or_service"),
    ),
  });
}

function fakeApiWithCompleteState(values: { constraints: string }): ProblemApi {
  return fakeApi({
    read: vi.fn().mockResolvedValue(completeProblemState(values)),
  });
}

function seedProblemSession(): void {
  sessionStorage.setItem(
    "observainova.problem-session.v1",
    JSON.stringify({
      problemId: "00000000-0000-4000-8000-000000000001",
      editToken: "test-edit-token",
    }),
  );
}

it("starts with the public problem instead of a catalog", async () => {
  render(<ProblemAssistant api={fakeApi()} />);
  expect(
    screen.getByRole("heading", { name: "Qual problema público você precisa enfrentar?" }),
  ).toBeInTheDocument();
  expect(screen.queryByText(/lista de teses/i)).not.toBeInTheDocument();
});

it("lets the user answer unknown without invented text", async () => {
  seedProblemSession();
  const api = fakeApiWithTerritoryQuestion();
  render(<ProblemAssistant api={api} />);
  await screen.findByText("Em qual território ou unidade administrativa isso acontece?");
  await userEvent.click(screen.getByRole("button", { name: "Não sei informar" }));
  expect(api.answer).toHaveBeenCalledWith(
    expect.any(String),
    expect.any(String),
    { field: "territory", value: null, knowledge_status: "unknown" },
  );
  expect(screen.queryByText(/território provável/i)).not.toBeInTheDocument();
});

it("reviews exact user wording before confirmation", async () => {
  seedProblemSession();
  const api = fakeApiWithCompleteState({ constraints: "Sem aumento de equipe" });
  render(<ProblemAssistant api={api} />);
  expect(await screen.findByText("Sem aumento de equipe")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Confirmar formulação" })).toBeEnabled();
});
```

Also test: edit token never renders in the DOM; API 404 clears the invalid browser session and returns to start; submission failure preserves typed text and offers retry; keyboard focus moves to the new assistant question; confirmation renders the handoff and no fabricated paths.

- [ ] **Step 3: Implement typed API client without token leakage**

`problem-api.ts` defines response types matching Task 4 and a private request helper:

```ts
async function problemRequest<T>(
  path: string,
  init: RequestInit,
  editToken?: string,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (editToken) headers.set("X-Problem-Token", editToken);
  const response = await fetch(`${apiBase}${path}`, { ...init, headers });
  if (!response.ok) throw await ProblemApiError.fromResponse(response);
  return (await response.json()) as T;
}
```

Do not log request headers or error objects containing request configuration. Export a real browser client and an interface that component tests can fake.

- [ ] **Step 4: Implement accessible assistant, review, and handoff states**

`app/page.tsx` renders `ProblemAssistant`. The component state machine is:

```text
start -> creating -> questioning -> reviewing -> confirming -> confirmed
                     \-> recoverable_error <-/
```

Required Portuguese copy:

- Start heading: `Qual problema público você precisa enfrentar?`
- Start support text: `Descreva a situação com suas palavras. Vamos organizar o contexto antes de buscar caminhos fundamentados na produção científica.`
- Unknown action: `Não sei informar`
- Review heading: `Foi isso que você quis dizer?`
- Confirm action: `Confirmar formulação`
- Handoff heading: `Problema confirmado`
- Handoff status: `O mapa será construído somente com contribuições científicas validadas. Nenhuma sugestão automática será apresentada como evidência.`

Use semantic `main`, `section`, `form`, `label`, `fieldset`, `button`, and `aria-live="polite"`. Never render the production catalog on this page. `ProblemReview` displays description, each field, and its status label (`Informado`, `Percepção`, `Não informado`).

- [ ] **Step 5: Add a restrained public visual system**

In `globals.css`, define high-contrast tokens and responsive containers without a design-system dependency:

```css
:root {
  --ink: #102a43;
  --muted: #52667a;
  --surface: #ffffff;
  --canvas: #f4f8fb;
  --primary: #075985;
  --primary-strong: #0c4a6e;
  --focus: #f59e0b;
  --border: #cbd5e1;
  --radius: 1rem;
}

:focus-visible {
  outline: 3px solid var(--focus);
  outline-offset: 3px;
}
```

Limit text measure to 72 characters, make touch targets at least 44px, preserve a single-column flow below 768px, and use no carousels, dashboard counters, production cards, or decorative graphs.

- [ ] **Step 6: Run component tests, typecheck, and production build**

Run:

```bash
cd apps/web
npm test
npm run typecheck
npm run build
```

Expected: all component tests pass, TypeScript reports no errors, and Next.js produces a successful production build.

- [ ] **Step 7: Commit the problem-first public application**

```bash
git add apps/web
git commit -m "feat: make public problem formulation the homepage"
```

### Task 6: Prove the complete first-phase scenario and document operation

**Files:**
- Create: `apps/web/playwright.config.ts`
- Create: `apps/web/e2e/problem-formulation.spec.ts`
- Modify: `infra/compose.yaml`
- Modify: `Makefile`
- Create: `docs/development/problem-formulation-flow.md`

**Interfaces:**
- Produces: a local `web` service on port 3000 connected to the API on port 8000.
- Produces: `make web-test`, `make web-build`, and an expanded `make check` covering backend and frontend.
- Produces: one Playwright journey from free description to confirmed version.

- [ ] **Step 1: Add a failing Playwright scenario**

Create `apps/web/e2e/problem-formulation.spec.ts`:

```ts
test("confirms a public problem without showing an unsupported solution", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Descreva o problema público").fill(
    "As pessoas aguardam muito por consultas especializadas",
  );
  await page.getByRole("button", { name: "Começar" }).click();

  const answers = [
    "Caruaru",
    "adultos aguardando cardiologia",
    "espera superior a 90 dias",
    "oferta insuficiente, segundo a equipe",
    "remanejamento manual de vagas",
    "equipe de regulação e dados de agenda",
    "sem aumento de equipe",
    "reduzir a espera preservando equidade",
  ];
  for (const answer of answers) {
    await page.getByLabel("Sua resposta").fill(answer);
    await page.getByRole("button", { name: "Continuar" }).click();
  }

  await expect(page.getByRole("heading", { name: "Foi isso que você quis dizer?" })).toBeVisible();
  await expect(page.getByText("sem aumento de equipe", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Confirmar formulação" }).click();
  await expect(page.getByRole("heading", { name: "Problema confirmado" })).toBeVisible();
  await expect(page.getByText(/somente com contribuições científicas validadas/i)).toBeVisible();
  await expect(page.getByText(/caminho recomendado/i)).toHaveCount(0);
});
```

Run it once before infrastructure wiring; expected failure is connection refused or missing web server.

- [ ] **Step 2: Add the web service and check targets**

Add a `web` service to `infra/compose.yaml` using `node:22-alpine`, working directory `/app`, command `npm install && npm run dev -- --hostname 0.0.0.0`, volume `../apps/web:/app`, environment `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1`, port `3000:3000`, and API health dependency.

Extend the root `Makefile`:

```make
.PHONY: web-test web-build e2e

web-test:
	cd apps/web && npm test && npm run typecheck

web-build:
	cd apps/web && npm run build

e2e:
	cd apps/web && npm run test:e2e

check: test lint typecheck web-test web-build runtime-smoke infra-check
```

- [ ] **Step 3: Document the exact local flow and security boundary**

Create `docs/development/problem-formulation-flow.md` with:

- start commands `docker compose -f infra/compose.yaml up --build`;
- browser URL `http://localhost:3000`;
- API URL `http://localhost:8000/docs`;
- migration command `cd apps/api && uv run alembic upgrade head`;
- the eight question fields in order;
- explanation that the raw edit token exists only in `sessionStorage` and loss of the token makes the private draft unrecoverable in this phase;
- explanation that confirmed problems show `awaiting_validated_contributions` because the validated-contribution and pathway plans are separate subprojects;
- recovery commands for stopping services without deleting volumes.

- [ ] **Step 4: Run the fresh full verification suite**

Run:

```bash
make test
make lint
make typecheck
make web-test
make web-build
make infra-check
docker compose -f infra/compose.yaml up -d --build postgres redis minio api web
cd apps/web && npm run test:e2e
docker compose -f infra/compose.yaml down
git diff --check
```

Expected evidence:

- backend: original 137 tests plus new problem tests pass with zero failures;
- Ruff: `All checks passed!`;
- mypy: no issues;
- frontend: all Vitest tests pass, TypeScript has zero errors, and Next.js build succeeds;
- Compose configuration is valid;
- Playwright completes the reference problem flow and verifies that no unsupported path is displayed;
- `git diff --check` prints no whitespace errors.

- [ ] **Step 5: Commit the verified first-phase vertical slice**

```bash
git add Makefile infra/compose.yaml apps/web/playwright.config.ts \
  apps/web/e2e/problem-formulation.spec.ts docs/development/problem-formulation-flow.md
git commit -m "test: verify problem formulation vertical slice"
```

## Subprojects Deliberately Separated from This Plan

The approved design contains four additional independently reviewable systems. They receive their own implementation plans after this slice because each has a different scientific and security boundary:

1. **Validated scientific contributions:** candidate claims, source spans, human review, publication/revocation, and strict public/private indexes.
2. **Solution-pathway map:** hybrid retrieval, contextual ranking, multi-contribution synthesis, evidence/maturity/barrier explanations, comparison, combination, and recalculation.
3. **Challenge Rooms:** proposal moderation, participants, decisions, adaptations, experiments, indicators, results, and learning.
4. **Thesis evaluation:** stratified sample, gold-standard coding, retrieval comparison, mediation measures, usability instruments, and exportable analytics.

The interface contract from this plan to the next one is a confirmed `ProblemContextVersion` plus `map_status="awaiting_validated_contributions"`. No later subsystem may read a mutable draft as if it were the user-approved problem.
