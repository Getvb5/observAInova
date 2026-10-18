import pytest
from alembic.config import Config

from alembic import command


def test_return_correction_migration_is_present_in_offline_ddl(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)

    ddl = capsys.readouterr().out
    assert "return_correction" in ddl
    assert "correction_base_version_id" in ddl
    assert "fk_review_cases_correction_base_version" in ddl
    assert "uq_review_cases_correction_base_version" in ddl
    assert "current_version_number" in ddl
