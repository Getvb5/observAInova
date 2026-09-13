import uuid
from datetime import date

import pytest
from alembic.config import Config
from sqlalchemy import delete, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from alembic import command
from pci.models.actors import Authorship, Organization, Person
from pci.models.enums import (
    HarvestStatus,
    ProductionType,
    RecordVisibility,
    TerritoryRelation,
)
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import AuditEvent, HarvestRun, RawRecord, Source
from pci.models.territory import ProductionTerritory, Territory


def test_raw_record_is_unique_per_source_identifier_and_checksum(session: Session) -> None:
    source = Source(
        code="fixture",
        name="Fixture Repository",
        connector_type="fixture",
        rights_policy="metadata_only",
    )
    session.add(source)
    session.flush()
    record = {
        "source_id": source.id,
        "source_identifier": "oai:fixture:1",
        "checksum": "abc123",
        "payload": {"title": "A"},
    }
    session.add(RawRecord(**record))
    session.commit()
    session.add(RawRecord(**record))
    with pytest.raises(IntegrityError):
        session.commit()


def test_production_version_never_overwrites_prior_version(session: Session) -> None:
    production = Production(canonical_key="doi:10.1/example")
    session.add(production)
    session.flush()
    session.add_all(
        [
            ProductionVersion(production_id=production.id, version=1, title="First"),
            ProductionVersion(production_id=production.id, version=2, title="Corrected"),
        ]
    )
    session.commit()
    versions = session.query(ProductionVersion).order_by(ProductionVersion.version).all()
    assert [item.title for item in versions] == ["First", "Corrected"]


def test_raw_record_rejects_updates(session: Session) -> None:
    source = Source(
        code="immutable-update-source",
        name="Immutable Update Source",
        connector_type="fixture",
        rights_policy="metadata_only",
    )
    record = RawRecord(
        source=source,
        source_identifier="immutable:update",
        checksum="checksum-update",
        payload={"title": "Original"},
    )
    session.add(record)
    session.commit()

    record.payload = {"title": "Overwritten"}
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()


def test_raw_record_rejects_deletes(session: Session) -> None:
    source = Source(
        code="immutable-delete-source",
        name="Immutable Delete Source",
        connector_type="fixture",
        rights_policy="metadata_only",
    )
    record = RawRecord(
        source=source,
        source_identifier="immutable:delete",
        checksum="checksum-delete",
        payload={"title": "Original"},
    )
    session.add(record)
    session.commit()

    session.delete(record)
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()


def test_production_version_rejects_updates(session: Session) -> None:
    production = Production(canonical_key="local:immutable-version-update")
    version = ProductionVersion(production=production, version=1, title="Original")
    session.add(version)
    session.commit()

    version.title = "Overwritten"
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()


def test_production_version_rejects_deletes(session: Session) -> None:
    production = Production(canonical_key="local:immutable-version-delete")
    version = ProductionVersion(production=production, version=1, title="Original")
    session.add(version)
    session.commit()

    session.delete(version)
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()


def test_postgresql_migration_enforces_append_only_history(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)
    ddl = " ".join(capsys.readouterr().out.split())

    assert "BEFORE UPDATE OR DELETE ON raw_records" in ddl
    assert "BEFORE UPDATE OR DELETE ON production_versions" in ddl
    assert (
        "FOREIGN KEY(production_id) REFERENCES productions (id) ON DELETE RESTRICT" in ddl
    )
    assert "CREATE TABLE raw_record_objects" in ddl
    assert "FOREIGN KEY(raw_record_id) REFERENCES raw_records (id) ON DELETE RESTRICT" in ddl


def test_postgresql_backfills_run_between_append_only_trigger_boundaries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)
    ddl = " ".join(capsys.readouterr().out.split())

    raw_drop = ddl.index("DROP TRIGGER raw_records_append_only ON raw_records")
    raw_backfill = ddl.index("UPDATE raw_records SET state_sequence")
    raw_recreate = ddl.index("CREATE TRIGGER raw_records_append_only", raw_drop + 1)
    version_drop = ddl.index(
        "DROP TRIGGER production_versions_append_only ON production_versions"
    )
    version_backfill = ddl.index("UPDATE production_versions SET")
    version_recreate = ddl.index(
        "CREATE TRIGGER production_versions_append_only", version_drop + 1
    )

    assert raw_drop < raw_backfill < raw_recreate
    assert version_drop < version_backfill < version_recreate


def test_orm_json_columns_compile_as_jsonb_for_postgresql_and_json_for_sqlite() -> None:
    expected_columns = {
        Source.__table__: ("schedule",),
        RawRecord.__table__: ("payload",),
        ProductionVersion.__table__: ("identifiers", "keywords", "normalization_report"),
        Person.__table__: ("identifiers",),
        Organization.__table__: ("identifiers",),
        AuditEvent.__table__: ("before", "after"),
    }

    for table, columns in expected_columns.items():
        postgresql_ddl = " ".join(
            str(CreateTable(table).compile(dialect=postgresql.dialect())).split()
        )
        for column in columns:
            assert f"{column} JSONB" in postgresql_ddl
            assert table.c[column].type.compile(dialect=sqlite.dialect()) == "JSON"


def test_domain_enums_expose_only_canonical_values() -> None:
    assert {item.value for item in HarvestStatus} == {
        "running",
        "completed",
        "partial",
        "failed",
    }
    assert {item.value for item in RecordVisibility} == {"private", "metadata_public"}
    assert {item.value for item in TerritoryRelation} == {"produced_in_pe", "about_pe"}
    assert {item.value for item in ProductionType} == {
        "article",
        "thesis",
        "dissertation",
        "undergraduate_work",
        "book",
        "book_chapter",
        "conference_paper",
        "technical_report",
        "research_project",
        "patent",
        "software",
        "dataset",
        "protocol",
        "method",
        "process",
        "social_technology",
        "educational_product",
        "technical_product",
        "other",
    }


def test_source_rejects_unknown_rights_policy(session: Session) -> None:
    session.add(
        Source(
            code="invalid-rights",
            name="Invalid Rights",
            connector_type="fixture",
            rights_policy="anything",
        )
    )
    with pytest.raises((IntegrityError, StatementError)):
        session.commit()


def test_version_links_optional_raw_record(session: Session) -> None:
    source = Source(
        code="version-source",
        name="Version Source",
        connector_type="fixture",
        rights_policy="link_only",
    )
    session.add(source)
    session.flush()
    record = RawRecord(
        source_id=source.id,
        source_identifier="record:1",
        checksum="def456",
        payload={"title": "Linked"},
    )
    production = Production(canonical_key="source:record:1")
    session.add_all([record, production])
    session.flush()
    session.add(
        ProductionVersion(
            production_id=production.id,
            raw_record_id=record.id,
            version=1,
            title="Linked",
            publication_date=date(2026, 9, 8),
        )
    )
    session.commit()
    version = session.query(ProductionVersion).one()
    assert version.raw_record_id == record.id


def test_authorship_can_identify_person_and_organization(session: Session) -> None:
    production = Production(canonical_key="local:authorship")
    person = Person(name="Ada Lovelace")
    organization = Organization(name="Analytical Society")
    session.add_all([production, person, organization])
    session.flush()
    session.add(
        Authorship(
            production_id=production.id,
            person_id=person.id,
            organization_id=organization.id,
            position=1,
        )
    )
    session.commit()
    authorship = session.query(Authorship).one()
    assert authorship.person_id == person.id
    assert authorship.organization_id == organization.id
    assert authorship.production.canonical_key == "local:authorship"
    assert authorship.person.name == "Ada Lovelace"
    assert authorship.organization is not None
    assert authorship.organization.name == "Analytical Society"


def test_authorship_without_organization_cannot_be_duplicated(session: Session) -> None:
    production = Production(canonical_key="local:authorship-without-organization")
    person = Person(name="Unique Author")
    session.add_all([production, person])
    session.flush()
    session.add_all(
        [
            Authorship(production_id=production.id, person_id=person.id, position=1),
            Authorship(production_id=production.id, person_id=person.id, position=1),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_production_accepts_both_territorial_relations(session: Session) -> None:
    production = Production(canonical_key="local:territory")
    territory = Territory(code="PE", name="Pernambuco")
    session.add_all([production, territory])
    session.flush()
    session.add_all(
        [
            ProductionTerritory(
                production_id=production.id,
                territory_id=territory.id,
                relation=TerritoryRelation.PRODUCED_IN_PE,
            ),
            ProductionTerritory(
                production_id=production.id,
                territory_id=territory.id,
                relation=TerritoryRelation.ABOUT_PE,
            ),
        ]
    )
    session.commit()
    relations = session.query(ProductionTerritory).all()
    assert {item.relation for item in relations} == {
        TerritoryRelation.PRODUCED_IN_PE,
        TerritoryRelation.ABOUT_PE,
    }


def test_foreign_key_rejects_orphan_raw_record(session: Session) -> None:
    session.add(
        RawRecord(
            source_id=uuid.uuid4(),
            source_identifier="orphan:1",
            checksum="orphan-checksum",
            payload={"title": "Orphan"},
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_foreign_key_rejects_authorship_with_orphan_person(session: Session) -> None:
    production = Production(canonical_key="local:orphan-authorship")
    session.add(production)
    session.flush()
    session.add(
        Authorship(
            production_id=production.id,
            person_id=uuid.uuid4(),
            position=1,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_production_with_versions_cannot_be_deleted(session: Session) -> None:
    production = Production(canonical_key="local:preserved-parent")
    session.add(ProductionVersion(production=production, version=1, title="Preserved"))
    session.commit()

    with pytest.raises(IntegrityError):
        session.execute(delete(Production).where(Production.id == production.id))


def test_deleting_organization_sets_authorship_organization_to_null(session: Session) -> None:
    production = Production(canonical_key="local:set-null")
    person = Person(name="Affiliated Author")
    organization = Organization(name="Former Institution")
    authorship = Authorship(
        production=production,
        person=person,
        organization=organization,
        position=1,
    )
    session.add(authorship)
    session.commit()

    session.execute(delete(Organization).where(Organization.id == organization.id))
    session.commit()
    session.expire(authorship)

    assert authorship.organization_id is None


def test_deleting_territory_cascades_its_production_association(session: Session) -> None:
    production = Production(canonical_key="local:cascade")
    territory = Territory(code="cascade-pe", name="Cascade Territory")
    session.add_all([production, territory])
    session.flush()
    session.add(
        ProductionTerritory(
            production_id=production.id,
            territory_id=territory.id,
            relation=TerritoryRelation.ABOUT_PE,
        )
    )
    session.commit()

    session.execute(delete(Territory).where(Territory.id == territory.id))
    session.commit()

    assert session.scalar(select(func.count()).select_from(ProductionTerritory)) == 0


def test_harvest_run_uses_canonical_status(session: Session) -> None:
    source = Source(
        code="harvest-source",
        name="Harvest Source",
        connector_type="fixture",
        rights_policy="open_copy",
    )
    session.add(source)
    session.flush()
    session.add(HarvestRun(source_id=source.id, status=HarvestStatus.PARTIAL))
    session.commit()
    assert session.query(HarvestRun).one().status is HarvestStatus.PARTIAL


def test_harvest_run_preserves_cursor_counts_and_rights_snapshot(session: Session) -> None:
    source = Source(
        code="counted-source",
        name="Counted Source",
        connector_type="fixture",
        rights_policy="institution_authorized_copy",
    )
    session.add(source)
    session.flush()
    run = HarvestRun(
        source_id=source.id,
        cursor="next-page",
        received=4,
        inserted=2,
        unchanged=1,
        failed=1,
    )
    session.add(run)
    session.flush()
    session.add(
        RawRecord(
            source_id=source.id,
            source_identifier="record:rights",
            checksum="fed654",
            payload={"title": "Rights"},
            rights_snapshot="CC-BY-4.0",
            source_url="https://repo.example/record:rights",
            harvest_run_id=run.id,
        )
    )
    session.commit()
    stored_run = session.query(HarvestRun).one()
    stored_record = session.query(RawRecord).one()
    assert (stored_run.cursor, stored_run.received, stored_run.inserted) == ("next-page", 4, 2)
    assert (stored_run.unchanged, stored_run.failed) == (1, 1)
    assert stored_record.rights_snapshot == "CC-BY-4.0"
    assert stored_record.source_url == "https://repo.example/record:rights"


def test_audit_event_records_its_timestamp(session: Session) -> None:
    event = AuditEvent(
        actor="curator@example.org",
        action="update",
        entity_type="production",
        entity_id=uuid.uuid4(),
        reason="Correction",
    )
    session.add(event)
    session.commit()
    assert AuditEvent.__table__.c.timestamp.type.timezone is True
