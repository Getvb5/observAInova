"""Separate source content equality from temporal state recurrence.

Revision ID: 0005_temporal_source_states
Revises: 0004_final_ingestion_hardening
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_temporal_source_states"
down_revision: str | None = "0004_final_ingestion_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("raw_records", sa.Column("state_sequence", sa.Integer(), nullable=True))
    op.execute("DROP TRIGGER raw_records_append_only ON raw_records")
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY source_id, source_identifier
                    ORDER BY collected_at, id
                ) AS state_sequence
            FROM raw_records
        )
        UPDATE raw_records
        SET state_sequence = ranked.state_sequence
        FROM ranked
        WHERE raw_records.id = ranked.id
        """
    )
    op.alter_column("raw_records", "state_sequence", nullable=False)
    op.execute(
        """
        CREATE TRIGGER raw_records_append_only
        BEFORE UPDATE OR DELETE ON raw_records
        FOR EACH ROW EXECUTE FUNCTION prevent_append_only_change()
        """
    )
    op.drop_constraint(
        "uq_raw_records_source_identifier_checksum",
        "raw_records",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_raw_records_source_identifier_state_sequence",
        "raw_records",
        ["source_id", "source_identifier", "state_sequence"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_raw_records_source_identifier_state_sequence",
        "raw_records",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_raw_records_source_identifier_checksum",
        "raw_records",
        ["source_id", "source_identifier", "checksum"],
    )
    op.drop_column("raw_records", "state_sequence")
