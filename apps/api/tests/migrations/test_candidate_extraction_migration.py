import pytest
from alembic.config import Config

from alembic import command


def test_candidate_extraction_migration_contains_private_grounded_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)
    ddl = " ".join(capsys.readouterr().out.split())

    assert "CREATE TABLE extraction_runs" in ddl
    assert "CREATE TABLE candidate_contributions" in ddl
    assert "CREATE TABLE candidate_claims" in ddl
    assert "CREATE TABLE candidate_groundings" in ddl
    assert "CREATE TYPE contribution_field AS ENUM" in ddl
    assert "CREATE TYPE contribution_type AS ENUM" in ddl
    assert "CREATE TYPE extraction_run_status AS ENUM" in ddl
    assert "CREATE TYPE candidate_status AS ENUM" in ddl
    assert "BEFORE UPDATE OR DELETE ON candidate_claims" in ddl
    assert "BEFORE UPDATE OR DELETE ON candidate_groundings" in ddl
