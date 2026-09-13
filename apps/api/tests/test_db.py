from pathlib import Path

import pytest
from sqlalchemy import select

from pci.db import session_scope
from pci.models import Base, Source


@pytest.fixture
def configured_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'session-scope.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "test")

    with session_scope() as session:
        Base.metadata.create_all(session.get_bind())


def test_session_scope_commits_successful_work(configured_database: None) -> None:
    with session_scope() as session:
        session.add(
            Source(
                code="committed",
                name="Committed Source",
                connector_type="fixture",
                rights_policy="metadata_only",
            )
        )

    with session_scope() as session:
        assert session.scalar(select(Source.code)) == "committed"


def test_session_scope_rolls_back_failed_work(configured_database: None) -> None:
    with pytest.raises(RuntimeError, match="stop"), session_scope() as session:
        session.add(
            Source(
                code="rolled-back",
                name="Rolled Back Source",
                connector_type="fixture",
                rights_policy="metadata_only",
            )
        )
        raise RuntimeError("stop")

    with session_scope() as session:
        assert session.scalar(select(Source.code).where(Source.code == "rolled-back")) is None
