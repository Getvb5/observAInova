import pytest
from alembic.config import Config

from alembic import command


def test_publication_projection_migration_has_outbox_and_safe_projection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)
    ddl = " ".join(capsys.readouterr().out.split())
    assert "CREATE TABLE publication_decisions" in ddl
    assert "CREATE TABLE publication_outbox" in ddl
    assert "CREATE TABLE published_contributions" in ddl
    assert "CREATE TYPE publication_action AS ENUM" in ddl
    assert "CREATE TYPE outbox_status AS ENUM" in ddl
