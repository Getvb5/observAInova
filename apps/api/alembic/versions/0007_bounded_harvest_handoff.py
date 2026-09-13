"""Persist harvest hand-off rows for bounded pipeline reads.

Revision ID: 0007_bounded_harvest_handoff
Revises: 0006_storage_attempt_ownership
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_bounded_harvest_handoff"
down_revision: str | None = "0006_storage_attempt_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "harvest_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("harvest_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["harvest_run_id"], ["harvest_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "harvest_run_id",
            "raw_record_id",
            name="uq_harvest_observations_run_raw_record",
        ),
        sa.UniqueConstraint(
            "harvest_run_id",
            "position",
            name="uq_harvest_observations_run_position",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER harvest_observations_append_only
        BEFORE UPDATE OR DELETE ON harvest_observations
        FOR EACH ROW EXECUTE FUNCTION prevent_append_only_change()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER harvest_observations_append_only ON harvest_observations")
    op.drop_table("harvest_observations")
