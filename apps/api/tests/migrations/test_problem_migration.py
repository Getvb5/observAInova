import pytest
from alembic.config import Config

from alembic import command


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
