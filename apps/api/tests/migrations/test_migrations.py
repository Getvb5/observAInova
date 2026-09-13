import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text


def test_storage_attempt_lease_migration_adds_and_removes_timestamp() -> None:
    """Keeping the lease column after downgrade would make rollback asymmetric."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE raw_record_objects (id VARCHAR PRIMARY KEY)"))
        migration_path = (
            Path(__file__).parents[2] / "alembic" / "versions" / "0009_storage_attempt_lease.py"
        )
        spec = importlib.util.spec_from_file_location(
            "storage_attempt_lease_migration", migration_path
        )
        assert spec is not None
        assert spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        operations = Operations(MigrationContext.configure(connection))
        original_op = migration.op
        migration.op = operations
        try:
            migration.upgrade()
            assert "attempt_started_at" in {
                column["name"] for column in inspect(connection).get_columns("raw_record_objects")
            }
            migration.downgrade()
            assert "attempt_started_at" not in {
                column["name"] for column in inspect(connection).get_columns("raw_record_objects")
            }
        finally:
            migration.op = original_op
    engine.dispose()
