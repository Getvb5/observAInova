import pytest
from alembic.config import Config

from alembic import command


def test_scientific_contributions_migration_has_explicit_versioned_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)
    ddl = " ".join(capsys.readouterr().out.split())

    assert "CREATE TABLE scientific_contributions" in ddl
    assert "CREATE TABLE contribution_versions" in ddl
    assert "CREATE TABLE review_field_decisions" in ddl
    assert "CREATE TABLE contribution_groundings" in ddl
    assert "CREATE TABLE contribution_candidate_sources" in ddl
    for field in (
        "problem_or_phenomenon", "contribution_type", "description", "mechanism",
        "population", "service", "territory", "methodology", "evidence_results",
        "barriers_limitations", "applicability", "required_resources", "maturity",
        "risks_contraindications",
    ):
        assert field in ddl
    assert "CREATE TYPE field_decision_action AS ENUM" in ddl
    assert "CREATE TYPE contribution_version_status AS ENUM" in ddl
