import uuid
from collections.abc import Mapping
from typing import cast

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from pci.ingestion.contracts import HarvestedRecord
from pci.models.actors import Authorship, Organization, Person
from pci.models.enums import RecordVisibility, RightsPolicy
from pci.models.production import DuplicateCandidate, Production, ProductionVersion
from pci.models.provenance import AuditEvent, RawRecord, Source
from pci.normalization.records import normalize_record
from pci.normalization.service import _production_for_source_provenance, persist_normalized_record
from pci.qualification.service import qualify_production


def _source(session: Session, code: str) -> Source:
    source = Source(
        code=code,
        name=code,
        connector_type="fixture",
        rights_policy=RightsPolicy.METADATA_ONLY,
    )
    session.add(source)
    session.flush()
    return source


def _raw(
    session: Session,
    source: Source,
    identifier: str,
    payload: dict[str, object],
) -> RawRecord:
    state_sequence = (
        session.scalar(
            select(func.max(RawRecord.state_sequence)).where(
                RawRecord.source_id == source.id,
                RawRecord.source_identifier == identifier,
            )
        )
        or 0
    ) + 1
    raw = RawRecord(
        source_id=source.id,
        source_identifier=identifier,
        payload=payload,
        checksum=uuid.uuid4().hex,
        state_sequence=state_sequence,
    )
    session.add(raw)
    session.flush()
    return raw


def test_source_identity_is_collision_safe_and_survives_a_source_code_rename(
    session: Session,
) -> None:
    """Source codes are mutable labels, not canonical provenance identity components."""
    colon_source = _source(session, "a:b")
    plain_source = _source(session, "a")
    first = _raw(
        session,
        colon_source,
        "c",
        {"title": "Colon source", "abstract": "Present"},
    )
    colliding_text = _raw(
        session,
        plain_source,
        "b:c",
        {"title": "Plain source", "abstract": "Present"},
    )

    first_production_id = persist_normalized_record(session, first.id)
    second_production_id = persist_normalized_record(session, colliding_text.id)
    first_production = session.get(Production, first_production_id)
    assert first_production is not None
    first_key = first_production.canonical_key

    colon_source.code = "renamed-source"
    renamed_observation = _raw(
        session,
        colon_source,
        "c",
        {"title": "Colon source corrected", "abstract": "Present"},
    )
    assert persist_normalized_record(session, renamed_observation.id) == first_production_id
    session.flush()

    assert first_production_id != second_production_id
    assert first_key == f"source:{colon_source.id}:c"
    assert session.get(Production, first_production_id).canonical_key == first_key  # type: ignore[union-attr]
    versions = session.scalars(
        select(ProductionVersion)
        .where(ProductionVersion.production_id == first_production_id)
        .order_by(ProductionVersion.version)
    ).all()
    assert [version.raw_record_id for version in versions] == [first.id, renamed_observation.id]


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
    production = Production(
        canonical_key=f"source:{source.code}:oai:legacy:one",
        current_version_number=1,
    )
    session.add(production)
    session.flush()
    session.add(
        ProductionVersion(
            production_id=production.id,
            raw_record_id=first_raw.id,
            version=1,
            title="Legacy continuity",
            abstract="Version one.",
            identifiers={"source": f"{source.code}:oai:legacy:one"},
        )
    )
    session.flush()
    production_id = production.id
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


def test_provenance_lookup_is_bounded_to_two_distinct_productions(
    session: Session,
) -> None:
    """Historical versions cannot make ambiguity detection load an unbounded result set."""
    source = _source(session, "bounded-provenance")
    history = [
        _raw(
            session,
            source,
            "oai:bounded:one",
            {"title": f"Historical version {version}"},
        )
        for version in range(1, 4)
    ]
    first = Production(canonical_key="bounded:first", current_version_number=2)
    second = Production(canonical_key="bounded:second", current_version_number=1)
    session.add_all([first, second])
    session.flush()
    session.add_all(
        [
            ProductionVersion(
                production_id=first.id,
                raw_record_id=history[0].id,
                version=1,
                title="Historical version 1",
            ),
            ProductionVersion(
                production_id=first.id,
                raw_record_id=history[1].id,
                version=2,
                title="Historical version 2",
            ),
            ProductionVersion(
                production_id=second.id,
                raw_record_id=history[2].id,
                version=1,
                title="Historical version 3",
            ),
        ]
    )
    session.flush()
    incoming = _raw(
        session,
        source,
        "oai:bounded:one",
        {"title": "Incoming historical version"},
    )
    statements: list[tuple[str, object]] = []

    def capture_provenance_query(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append((statement, parameters))

    event.listen(session.bind, "before_cursor_execute", capture_provenance_query)
    try:
        with pytest.raises(ValueError, match="ambiguous source provenance"):
            _production_for_source_provenance(session, incoming)
    finally:
        event.remove(session.bind, "before_cursor_execute", capture_provenance_query)

    assert len(statements) == 1
    statement, parameters = statements[0]
    assert "SELECT DISTINCT" in statement.upper()
    assert "LIMIT" in statement.upper()
    bound_parameters = (
        parameters.values()
        if isinstance(parameters, Mapping)
        else cast(tuple[object, ...], parameters)
    )
    assert 2 in bound_parameters


def test_resolved_author_aliases_are_deduplicated_without_collapsing_bare_homonyms(
    session: Session,
) -> None:
    """Only a shared resolved identity may collapse aliases; bare names stay unverified."""
    source = _source(session, "author-resolution")
    raw = _raw(
        session,
        source,
        "authors:1",
        {
            "title": "Resolved author aliases",
            "abstract": "Present",
            "authors": [
                {
                    "name": "Ana Silva",
                    "orcid": "https://orcid.org/0000-0002-1825-0097",
                    "organization": "Institute A",
                },
                {
                    "name": "A. Silva",
                    "orcid": "0000 0002 1825 0097",
                    "organization": "Institute A",
                },
                {
                    "name": "Ana Silva",
                    "orcid": "ORCID: 0000-0002-1825-0097",
                    "organization": "Institute B",
                },
                "Ana Silva",
            ],
        },
    )

    production_id = persist_normalized_record(session, raw.id)
    session.flush()
    authorships = session.execute(
        select(Authorship, Person, Organization)
        .join(Person, Person.id == Authorship.person_id)
        .outerjoin(Organization, Organization.id == Authorship.organization_id)
        .where(Authorship.production_id == production_id)
        .order_by(Authorship.position)
    ).all()
    version = session.scalar(
        select(ProductionVersion).where(ProductionVersion.production_id == production_id)
    )

    assert [
        (person.name, organization.name if organization is not None else None)
        for _, person, organization in authorships
    ] == [
        ("Ana Silva", "Institute A"),
        ("Ana Silva", "Institute B"),
        ("Ana Silva", None),
    ]
    identified_people = {
        authorship.person_id
        for authorship, person, _ in authorships
        if person.identifiers == {"orcid": "0000-0002-1825-0097"}
    }
    bare_people = {
        authorship.person_id for authorship, person, _ in authorships if person.identifiers is None
    }
    assert len(identified_people) == 1
    assert len(bare_people) == 1
    assert identified_people.isdisjoint(bare_people)
    assert version is not None
    assert any(
        change.get("field") == "authors[1]"
        and change.get("reason") == "resolved_identity_duplicate_discarded"
        for change in version.normalization_report["transformations"]
    )
    assert (
        session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "authorship.alias_discarded",
                AuditEvent.entity_id == production_id,
            )
        )
        is not None
    )


def test_multivalued_scalar_fields_report_each_discard_deterministically() -> None:
    """Selecting a scalar must never silently erase later source values."""
    raw = HarvestedRecord(
        "oai:final:multivalue",
        {
            "title": ["First title", "Second title"],
            "abstract": ["First abstract", "Second abstract"],
            "language": ["PT-BR", "en"],
            "date": ["2024", "2023"],
            "doi": ["10.1000/FIRST", "10.1000/SECOND"],
            "identifiers": ["https://doi.org/10.1000/THIRD", "https://doi.org/10.1000/FOURTH"],
        },
        "https://repo.example/items/multivalue",
        "metadata-only",
    )

    normalized = normalize_record(raw)
    transformations = normalized.normalization_report["transformations"]

    assert normalized.title == "First title"
    assert normalized.abstract == "First abstract"
    assert normalized.language == "pt-br"
    assert normalized.publication_year == 2024
    assert normalized.identifiers["doi"] == "10.1000/first"
    for field in ("title[1]", "abstract[1]", "language[1]", "date[1]", "doi[1]"):
        assert any(
            change.get("field") == field and change.get("reason") == "multiple_values_discarded"
            for change in transformations
        )
    assert any(
        change.get("field") == "identifiers[1].doi"
        and change.get("reason") == "duplicate_discarded"
        for change in transformations
    )
    assert raw.payload["title"] == ["First title", "Second title"]


def test_structural_qualification_keeps_pending_duplicate_candidates_private(
    session: Session,
) -> None:
    """The automatic gate may publish metadata, but never an ambiguous duplicate."""
    source = _source(session, "qualification-review")
    existing_raw = _raw(
        session,
        source,
        "existing",
        {"title": "Água e inovação", "abstract": "Existing", "date": "2024"},
    )
    existing_id = persist_normalized_record(session, existing_raw.id)
    assert qualify_production(session, existing_id).published is True
    candidate_raw = _raw(
        session,
        source,
        "candidate",
        {"title": "Agua e inovacao", "abstract": "Candidate", "date": "2024"},
    )

    candidate_id = persist_normalized_record(session, candidate_raw.id)
    result = qualify_production(session, candidate_id)
    candidate = session.get(Production, candidate_id)

    assert result.eligible is False
    assert result.published is False
    assert result.reasons == ("pending duplicate candidate",)
    assert candidate is not None
    assert candidate.visibility is RecordVisibility.PRIVATE
    assert (
        session.scalar(
            select(DuplicateCandidate).where(DuplicateCandidate.production_id == candidate_id)
        )
        is not None
    )
    assert (
        session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "metadata.qualification_rejected",
                AuditEvent.entity_id == candidate_id,
            )
        )
        is not None
    )


def test_new_normalized_version_returns_a_public_production_to_private_until_requalified(
    session: Session,
) -> None:
    """A new current version cannot inherit publication without a fresh structural check."""
    source = _source(session, "qualification-version")
    first = _raw(
        session,
        source,
        "versioned",
        {"title": "First structural version", "abstract": "Present"},
    )
    production_id = persist_normalized_record(session, first.id)
    assert qualify_production(session, production_id).published is True
    second = _raw(
        session,
        source,
        "versioned",
        {"title": "Second structural version", "abstract": "Present"},
    )

    assert persist_normalized_record(session, second.id) == production_id
    production = session.get(Production, production_id)

    assert production is not None
    assert production.visibility is RecordVisibility.PRIVATE
    assert qualify_production(session, production_id).published is True
    assert production.visibility is RecordVisibility.METADATA_PUBLIC
