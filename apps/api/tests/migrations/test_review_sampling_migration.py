import pytest
from alembic.config import Config

from alembic import command


def test_review_sampling_migration_contains_auditable_assignments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)
    ddl = " ".join(capsys.readouterr().out.split())

    assert "CREATE TABLE sampling_runs" in ddl
    assert "CREATE TABLE review_cases" in ddl
    assert "CREATE TABLE review_assignments" in ddl
    assert "CREATE TYPE sample_split AS ENUM" in ddl
    assert "CREATE TYPE review_case_kind AS ENUM" in ddl
    assert "CREATE TYPE review_lane AS ENUM" in ddl
    assert "CREATE TYPE review_status AS ENUM" in ddl
    assert "candidate_contribution_id IS NOT NULL" in ddl
    assert "published_contribution_version_id IS NOT NULL" in ddl
    assert "UNIQUE (review_case_id, lane)" in ddl
