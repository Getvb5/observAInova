import pytest
from alembic.config import Config

from alembic import command


def test_governance_integrity_migration_protects_all_immutable_history(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)
    ddl = " ".join(capsys.readouterr().out.split())

    for table in (
        "review_field_decisions",
        "contribution_candidate_sources",
        "contribution_groundings",
        "publication_decisions",
    ):
        assert f"CREATE TRIGGER trg_{table}_append_only" in ddl
