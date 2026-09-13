import uuid
from collections.abc import Mapping
from datetime import date
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import event, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import pci.normalization.service as normalization_service
from alembic import command
from pci.ingestion.contracts import HarvestedRecord
from pci.models.actors import Authorship, Organization, Person
from pci.models.production import DuplicateCandidate, Production, ProductionVersion
from pci.models.provenance import AuditEvent, RawRecord, Source
from pci.normalization.contracts import MatchDecision
from pci.normalization.deduplication import match_production
from pci.normalization.records import normalize_record
from pci.normalization.service import _production_lock_statement, persist_normalized_record
from pci.normalization.text import exact_text_key


def _normalized_record(**payload: object):
    complete = {
        "title": "A distinct title",
        "abstract": "Available",
        "date": "2024",
        "authors": ["Ana Silva"],
    }
    complete.update(payload)
    return normalize_record(
        HarvestedRecord(
            source_identifier="external:record",
            payload=complete,
            source_url=None,
            rights=None,
        )
    )


def _existing_production(
    session: Session,
    *,
    key: str,
    title: str,
    year: int = 2024,
    identifiers: Mapping[str, str] | None = None,
    author: str | None = "Ana Silva",
) -> Production:
    production = Production(canonical_key=key, current_version_number=1)
    session.add(production)
    session.flush()
    session.add(
        ProductionVersion(
            production_id=production.id,
            version=1,
            title=title,
            title_digest=normalization_service.matching_digest(exact_text_key(title)),
            publication_date=date(year, 1, 1),
            identifiers=dict(identifiers or {}),
            doi_digest=(
                normalization_service.matching_digest(identifiers["doi"])
                if identifiers is not None and "doi" in identifiers
                else None
            ),
            patent_digest=(
                normalization_service.matching_digest(identifiers["patent"])
                if identifiers is not None and "patent" in identifiers
                else None
            ),
            handle_digest=(
                normalization_service.matching_digest(identifiers["handle"])
                if identifiers is not None and "handle" in identifiers
                else None
            ),
            source_digest=(
                normalization_service.matching_digest(identifiers["source"])
                if identifiers is not None and "source" in identifiers
                else None
            ),
        )
    )
    if author is not None:
        person = Person(
            name=author,
            name_digest=normalization_service.matching_digest(exact_text_key(author)),
        )
        session.add(person)
        session.flush()
        session.add(Authorship(production_id=production.id, person_id=person.id, position=1))
    session.flush()
    return production


def _source(session: Session, code: str = "normalization") -> Source:
    source = Source(
        code=code,
        name=f"{code} source",
        connector_type="fixture",
        rights_policy="metadata_only",
    )
    session.add(source)
    session.flush()
    return source


def _raw_record(
    session: Session,
    source: Source,
    *,
    source_identifier: str,
    checksum: str,
    payload: dict[str, Any],
) -> RawRecord:
    state_sequence = (
        session.scalar(
            select(func.max(RawRecord.state_sequence)).where(
                RawRecord.source_id == source.id,
                RawRecord.source_identifier == source_identifier,
            )
        )
        or 0
    ) + 1
    raw = RawRecord(
        source_id=source.id,
        source_identifier=source_identifier,
        checksum=checksum,
        state_sequence=state_sequence,
        payload=payload,
        source_url="https://repository.example/records/1",
        rights_snapshot="metadata-only",
    )
    session.add(raw)
    session.flush()
    return raw


def test_exact_identifier_wins_before_a_different_similar_title(session: Session) -> None:
    doi_match = _existing_production(
        session,
        key="doi:10.1000/one",
        title="Completely unrelated",
        identifiers={"doi": "10.1000/one"},
    )
    _existing_production(
        session,
        key="local:similar",
        title="Água e inovação sustentável",
        author=None,
    )

    decision = match_production(
        session,
        _normalized_record(
            title="Agua e inovacao sustentavel",
            doi="https://doi.org/10.1000/ONE",
        ),
    )

    assert decision.kind == "exact"
    assert decision.production_id == doi_match.id
    assert decision.reasons == ("exact identifier: doi",)


def test_exact_title_year_and_normalized_author_matches(session: Session) -> None:
    existing = _existing_production(
        session,
        key="local:authored",
        title="Ciência Aberta",
        author="João da Silva",
    )

    decision = match_production(
        session,
        _normalized_record(title="ciência aberta", authors=["  JOÃO\u00a0DA SILVA  "]),
    )

    assert decision.kind == "exact"
    assert decision.production_id == existing.id
    assert decision.reasons == ("exact title, publication year, and author",)


def test_title_similarity_at_or_above_point_nine_is_review(session: Session) -> None:
    existing = _existing_production(
        session,
        key="local:threshold-review",
        title="abcdefghijklmnopqrst",
        author=None,
    )

    decision = match_production(
        session,
        _normalized_record(title="abcdefghijklmnopqrstu", authors=[]),
    )

    assert decision.kind == "review"
    assert decision.production_id == existing.id
    assert decision.score == pytest.approx(40 / 43)
    assert decision.reasons == (
        "title trigram similarity 0.930 at or above 0.900",
        "compatible publication year",
    )


def test_title_similarity_below_point_nine_is_new(session: Session) -> None:
    _existing_production(
        session,
        key="local:threshold-new",
        title="abcdefgh",
        author=None,
    )

    decision = match_production(
        session,
        _normalized_record(title="abcdefghi", authors=[]),
    )

    assert decision.kind == "new"
    assert decision.production_id is None
    assert decision.reasons == ("no conservative duplicate match",)


def test_title_similarity_without_a_compatible_year_or_author_is_new(session: Session) -> None:
    _existing_production(
        session,
        key="local:insufficient-evidence",
        title="Água e inovação",
        author=None,
    )

    decision = match_production(
        session,
        _normalized_record(title="Agua e inovacao", date=None, authors=[]),
    )

    assert decision.kind == "new"
    assert decision.production_id is None


def test_catalog_matching_queries_only_a_bounded_candidate_set(
    session: Session,
) -> None:
    for index in range(125):
        _existing_production(
            session,
            key=f"local:bounded-{index:03d}",
            title=f"Bounded catalog title {index:03d}",
            author=None,
        )
    statements: list[str] = []

    def capture_queries(
        _: object,
        __: object,
        statement: str,
        parameters: object,
        ___: object,
        ____: object,
    ) -> None:
        del parameters
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "productions" in statement
            and "production_versions" in statement
        ):
            statements.append(statement)

    assert session.bind is not None
    event.listen(session.bind, "before_cursor_execute", capture_queries)
    try:
        decision = match_production(
            session,
            _normalized_record(
                title="A title absent from the bounded catalog",
                authors=[],
            ),
        )
    finally:
        event.remove(session.bind, "before_cursor_execute", capture_queries)

    assert decision.kind == "new"
    assert 1 <= len(statements) <= 2
    assert all(" LIMIT " in statement.upper() for statement in statements)


def test_person_and_organization_resolution_never_full_scan_per_record(
    session: Session,
) -> None:
    source = _source(session, "bounded-actors")
    session.add_all(Person(name=f"Existing person {index:03d}") for index in range(125))
    session.add_all(Organization(name=f"Existing organization {index:03d}") for index in range(125))
    session.flush()
    raw = _raw_record(
        session,
        source,
        source_identifier="bounded-actors:1",
        checksum="bounded-actors-checksum",
        payload={
            "title": "Bounded actor lookup",
            "abstract": "Present",
            "authors": [
                {
                    "name": "New bounded person",
                    "organization": "New bounded organization",
                }
            ],
            "institution": "New producing organization",
        },
    )
    actor_queries: list[str] = []

    def capture_queries(
        _: object,
        __: object,
        statement: str,
        parameters: object,
        ___: object,
        ____: object,
    ) -> None:
        del parameters
        normalized = " ".join(statement.lower().split())
        if " from people" in normalized or " from organizations" in normalized:
            actor_queries.append(normalized)

    assert session.bind is not None
    event.listen(session.bind, "before_cursor_execute", capture_queries)
    try:
        persist_normalized_record(session, raw.id)
    finally:
        event.remove(session.bind, "before_cursor_execute", capture_queries)

    assert actor_queries
    assert all(" where " in statement for statement in actor_queries)
    assert all(" limit " in statement for statement in actor_queries)


def test_review_creates_private_provisional_production_without_merging(
    session: Session,
) -> None:
    existing = _existing_production(
        session,
        key="local:existing-review",
        title="Água e inovação",
        year=2023,
        author=None,
    )
    source = _source(session)
    raw = _raw_record(
        session,
        source,
        source_identifier="review:1",
        checksum="review-checksum",
        payload={
            "title": "Agua e inovacao",
            "abstract": "New source",
            "date": "2023",
        },
    )

    provisional_id = persist_normalized_record(session, raw.id)
    session.flush()

    assert provisional_id != existing.id
    provisional = session.get(Production, provisional_id)
    assert provisional is not None
    assert provisional.visibility.value == "private"
    assert (
        session.scalar(
            select(func.count())
            .select_from(ProductionVersion)
            .where(ProductionVersion.production_id == existing.id)
        )
        == 1
    )
    candidate = session.scalar(select(DuplicateCandidate))
    assert candidate is not None
    assert candidate.production_id == provisional_id
    assert candidate.candidate_production_id == existing.id
    assert candidate.status == "pending"
    assert candidate.reviewer is None
    assert candidate.reasons == [
        "title trigram similarity 1.000 at or above 0.900",
        "compatible publication year",
    ]

    audit_actions = set(session.scalars(select(AuditEvent.action)))
    assert {
        "production.created",
        "production_version.created",
        "duplicate_candidate.created",
    } <= audit_actions
    candidate_audit = session.scalar(
        select(AuditEvent).where(AuditEvent.action == "duplicate_candidate.created")
    )
    assert candidate_audit is not None
    assert candidate_audit.reason is not None
    assert "title trigram similarity" in candidate_audit.reason


def test_exact_match_appends_version_and_same_raw_record_is_idempotent(
    session: Session,
) -> None:
    existing = _existing_production(
        session,
        key="doi:10.2000/versioned",
        title="Original title",
        identifiers={"doi": "10.2000/versioned"},
    )
    source = _source(session)
    raw = _raw_record(
        session,
        source,
        source_identifier="versioned:2",
        checksum="versioned-checksum",
        payload={
            "title": "Updated title",
            "abstract": "Updated abstract",
            "doi": "10.2000/VERSIONED",
            "authors": [
                {
                    "name": "Ada Lovelace",
                    "orcid": "0000-0002-1825-0097",
                    "institution": "Analytical Society",
                }
            ],
        },
    )

    first_id = persist_normalized_record(session, raw.id)
    second_id = persist_normalized_record(session, raw.id)
    session.flush()

    assert first_id == second_id == existing.id
    versions = list(
        session.scalars(
            select(ProductionVersion)
            .where(ProductionVersion.production_id == existing.id)
            .order_by(ProductionVersion.version)
        )
    )
    assert [(version.version, version.title) for version in versions] == [
        (1, "Original title"),
        (2, "Updated title"),
    ]
    assert versions[1].raw_record_id == raw.id
    assert versions[1].normalization_report is not None
    assert existing.current_version_number == 2
    assert session.scalar(select(func.count()).select_from(Person)) == 2
    assert (
        session.scalar(
            select(func.count()).select_from(Person).where(Person.name == "Ada Lovelace")
        )
        == 1
    )
    assert session.scalar(select(func.count()).select_from(Organization)) == 1


def test_top_level_organization_is_not_inferred_as_an_author_affiliation(
    session: Session,
) -> None:
    source = _source(session)
    raw = _raw_record(
        session,
        source,
        source_identifier="organization:1",
        checksum="organization-checksum",
        payload={
            "title": "No inferred affiliation",
            "abstract": "Present",
            "institution": "Federal University",
            "authors": ["Ada Lovelace"],
        },
    )

    production_id = persist_normalized_record(session, raw.id)
    authorship = session.scalar(select(Authorship).where(Authorship.production_id == production_id))

    assert authorship is not None
    assert authorship.organization_id is None
    assert session.scalar(select(func.count()).select_from(Organization)) == 1


def test_new_version_synchronizes_current_authorship_with_audit_history(
    session: Session,
) -> None:
    source = _source(session)
    first = _raw_record(
        session,
        source,
        source_identifier="authorship:1",
        checksum="authorship-first",
        payload={
            "title": "Current authorship",
            "abstract": "First version",
            "doi": "10.2000/authorship",
            "authors": [
                {"name": "Alice Andrade", "organization": "Instituto Alice"},
                {"name": "Bruno Barros", "organization": "Instituto Antigo"},
            ],
        },
    )
    second = _raw_record(
        session,
        source,
        source_identifier="authorship:2",
        checksum="authorship-second",
        payload={
            "title": "Current authorship",
            "abstract": "Second version",
            "doi": "10.2000/authorship",
            "authors": [
                {"name": "Bruno Barros", "organization": "Instituto Atual"},
                "Carla Costa",
            ],
        },
    )

    production_id = persist_normalized_record(session, first.id)
    assert persist_normalized_record(session, second.id) == production_id
    session.flush()

    current_authors = list(
        session.execute(
            select(Authorship, Person.name, Organization.name)
            .join(Person, Person.id == Authorship.person_id)
            .outerjoin(Organization, Organization.id == Authorship.organization_id)
            .where(Authorship.production_id == production_id)
            .order_by(Authorship.position)
        )
    )
    assert [
        (authorship.position, person_name, organization_name)
        for authorship, person_name, organization_name in current_authors
    ] == [
        (1, "Bruno Barros", "Instituto Atual"),
        (2, "Carla Costa", None),
    ]

    bruno_authorship = current_authors[0][0]
    update = session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "authorship.updated",
            AuditEvent.entity_id == bruno_authorship.id,
        )
    )
    assert update is not None
    assert update.before is not None
    assert update.after is not None
    assert update.before["position"] == 2
    assert update.after["position"] == 1
    assert update.before["organization_id"] != update.after["organization_id"]

    removed = session.scalar(select(AuditEvent).where(AuditEvent.action == "authorship.removed"))
    assert removed is not None
    assert removed.before is not None
    alice = session.scalar(select(Person).where(Person.name == "Alice Andrade"))
    assert alice is not None
    assert removed.before["person_id"] == str(alice.id)
    assert first.payload["authors"][0]["organization"] == "Instituto Alice"
    assert second.payload["authors"][1] == "Carla Costa"


def test_new_version_preserves_an_existing_exact_affiliation_before_reassigning(
    session: Session,
) -> None:
    source = _source(session)
    first = _raw_record(
        session,
        source,
        source_identifier="multiple-affiliations:1",
        checksum="multiple-affiliations-first",
        payload={
            "title": "Multiple affiliations",
            "abstract": "First version",
            "doi": "10.2000/multiple-affiliations",
            "authors": [{"name": "Ana Silva", "organization": "Institute A"}],
        },
    )
    second = _raw_record(
        session,
        source,
        source_identifier="multiple-affiliations:2",
        checksum="multiple-affiliations-second",
        payload={
            "title": "Multiple affiliations",
            "abstract": "Second version",
            "doi": "10.2000/multiple-affiliations",
            "authors": [
                {"name": "Ana Silva", "organization": "Institute B"},
                {"name": "Ana Silva", "organization": "Institute A"},
            ],
        },
    )

    production_id = persist_normalized_record(session, first.id)
    assert persist_normalized_record(session, second.id) == production_id
    session.flush()

    current_authors = list(
        session.execute(
            select(Authorship.position, Person.name, Organization.name)
            .join(Person, Person.id == Authorship.person_id)
            .join(Organization, Organization.id == Authorship.organization_id)
            .where(Authorship.production_id == production_id)
            .order_by(Authorship.position)
        )
    )
    assert current_authors == [
        (1, "Ana Silva", "Institute B"),
        (2, "Ana Silva", "Institute A"),
    ]


def test_partial_publication_year_is_persisted_without_an_invented_date(
    session: Session,
) -> None:
    source = _source(session)
    raw = _raw_record(
        session,
        source,
        source_identifier="partial-year:1",
        checksum="partial-year-checksum",
        payload={"title": "Year only", "abstract": "Present", "date": "2024"},
    )

    production_id = persist_normalized_record(session, raw.id)
    version = session.scalar(
        select(ProductionVersion).where(ProductionVersion.production_id == production_id)
    )

    assert version is not None
    assert version.publication_date is None
    assert version.publication_year == 2024


def test_exact_title_year_author_uses_preserved_partial_year(session: Session) -> None:
    production = Production(canonical_key="local:partial-year-match", current_version_number=1)
    session.add(production)
    session.flush()
    session.add(
        ProductionVersion(
            production_id=production.id,
            version=1,
            title="Year precision",
            title_digest=normalization_service.matching_digest("year precision"),
            publication_year=2024,
        )
    )
    person = Person(
        name="Ada Lovelace",
        name_digest=normalization_service.matching_digest("ada lovelace"),
    )
    session.add(person)
    session.flush()
    session.add(Authorship(production_id=production.id, person_id=person.id, position=1))
    session.flush()

    decision = match_production(
        session,
        _normalized_record(title="year precision", date="2024", authors=["Ada Lovelace"]),
    )

    assert decision.kind == "exact"
    assert decision.production_id == production.id


def test_updated_payload_for_same_source_identifier_adds_a_version(session: Session) -> None:
    source = _source(session)
    first = _raw_record(
        session,
        source,
        source_identifier="stable:1",
        checksum="stable-first",
        payload={"title": "First", "abstract": "Version one"},
    )
    second = _raw_record(
        session,
        source,
        source_identifier="stable:1",
        checksum="stable-second",
        payload={"title": "Second", "abstract": "Version two"},
    )

    production_id = persist_normalized_record(session, first.id)
    assert persist_normalized_record(session, second.id) == production_id
    session.flush()

    versions = list(
        session.scalars(
            select(ProductionVersion)
            .where(ProductionVersion.production_id == production_id)
            .order_by(ProductionVersion.version)
        )
    )
    assert [item.title for item in versions] == ["First", "Second"]
    assert [item.raw_record_id for item in versions] == [first.id, second.id]


def test_maximum_source_identifier_keeps_a_valid_canonical_key(
    session: Session,
) -> None:
    source = _source(session, "maximum-source-identity")
    source_identifier = "x" * 1024
    raw = _raw_record(
        session,
        source,
        source_identifier=source_identifier,
        checksum="maximum-source-identity-checksum",
        payload={"title": "Maximum source identity", "abstract": "Present"},
    )

    production_id = persist_normalized_record(session, raw.id)
    production = session.get(Production, production_id)
    version = session.scalar(
        select(ProductionVersion).where(ProductionVersion.production_id == production_id)
    )

    assert production is not None
    assert version is not None
    assert len(production.canonical_key) <= 1024
    assert version.identifiers is not None
    assert version.identifiers["source"] == f"{source.id}:{source_identifier}"


def test_missing_title_rejects_before_creating_a_production(session: Session) -> None:
    source = _source(session)
    raw = _raw_record(
        session,
        source,
        source_identifier="missing-title:1",
        checksum="missing-title",
        payload={"abstract": "No title"},
    )

    with pytest.raises(ValueError, match="title is required"):
        persist_normalized_record(session, raw.id)

    assert session.scalar(select(func.count()).select_from(Production)) == 0
    assert session.scalar(select(func.count()).select_from(ProductionVersion)) == 0
    assert raw.payload == {"abstract": "No title"}


def test_database_rejects_two_versions_for_one_raw_record(session: Session) -> None:
    source = _source(session)
    raw = _raw_record(
        session,
        source,
        source_identifier="unique-raw:1",
        checksum="unique-raw",
        payload={"title": "Unique", "abstract": "Present"},
    )
    first = Production(canonical_key="local:first")
    second = Production(canonical_key="local:second")
    session.add_all([first, second])
    session.flush()
    session.add_all(
        [
            ProductionVersion(
                production_id=first.id,
                raw_record_id=raw.id,
                version=1,
                title="First",
            ),
            ProductionVersion(
                production_id=second.id,
                raw_record_id=raw.id,
                version=1,
                title="Second",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.flush()


def test_raw_record_unique_conflict_converges_to_the_existing_production(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(session)
    raw = _raw_record(
        session,
        source,
        source_identifier="race:1",
        checksum="race-checksum",
        payload={"title": "Race", "abstract": "Present"},
    )
    winner = Production(canonical_key="source:normalization:race:1", current_version_number=1)
    session.add(winner)
    session.flush()
    session.add(
        ProductionVersion(
            production_id=winner.id,
            raw_record_id=raw.id,
            version=1,
            title="Race",
            identifiers={"source": "normalization:race:1"},
        )
    )
    session.flush()

    original_scalar = session.scalar
    stale_read = True

    def scalar_with_one_stale_raw_lookup(*args: object, **kwargs: object) -> object:
        nonlocal stale_read
        if stale_read:
            stale_read = False
            return None
        return original_scalar(*args, **kwargs)

    monkeypatch.setattr(session, "scalar", scalar_with_one_stale_raw_lookup)

    assert persist_normalized_record(session, raw.id) == winner.id


def test_canonical_key_conflict_after_a_stale_new_decision_uses_winner_version(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(session)
    winner_raw = _raw_record(
        session,
        source,
        source_identifier="canonical-race:1",
        checksum="canonical-winner",
        payload={"title": "Canonical race", "abstract": "Winner"},
    )
    losing_raw = _raw_record(
        session,
        source,
        source_identifier="canonical-race:1",
        checksum="canonical-loser",
        payload={"title": "Canonical race", "abstract": "Loser"},
    )
    source_identity = f"{source.id}:canonical-race:1"
    winner = Production(
        canonical_key=f"source:{source_identity}",
        current_version_number=1,
    )
    session.add(winner)
    session.flush()
    session.add(
        ProductionVersion(
            production_id=winner.id,
            raw_record_id=winner_raw.id,
            version=1,
            title="Canonical race",
            identifiers={"source": source_identity},
        )
    )
    session.flush()

    original_match = normalization_service.match_production
    stale_decision = True

    def match_new_once(*args: object, **kwargs: object) -> MatchDecision:
        nonlocal stale_decision
        if stale_decision:
            stale_decision = False
            return MatchDecision("new", None, ("stale new decision",))
        return original_match(*args, **kwargs)

    monkeypatch.setattr(normalization_service, "match_production", match_new_once)

    assert persist_normalized_record(session, losing_raw.id) == winner.id
    versions = list(
        session.scalars(
            select(ProductionVersion)
            .where(ProductionVersion.production_id == winner.id)
            .order_by(ProductionVersion.version)
        )
    )
    assert [(version.version, version.raw_record_id) for version in versions] == [
        (1, winner_raw.id),
        (2, losing_raw.id),
    ]


def test_version_allocation_locks_the_production_row_on_postgresql() -> None:
    statement = _production_lock_statement(uuid.uuid4())

    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))


def test_postgresql_migration_adds_duplicate_candidates_and_raw_id_uniqueness(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)
    ddl = " ".join(capsys.readouterr().out.split())

    assert "CREATE TABLE duplicate_candidates" in ddl
    assert "CONSTRAINT uq_production_versions_raw_record UNIQUE (raw_record_id)" in ddl
    assert "FOREIGN KEY(production_id) REFERENCES productions (id) ON DELETE RESTRICT" in ddl
    assert (
        "FOREIGN KEY(candidate_production_id) REFERENCES productions (id) ON DELETE RESTRICT" in ddl
    )
    assert "status VARCHAR(32) DEFAULT 'pending' NOT NULL" in ddl
    assert "reviewer VARCHAR(255)" in ddl
    assert "ADD COLUMN publication_year INTEGER" in ddl
