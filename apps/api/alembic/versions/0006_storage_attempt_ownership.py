"""Add attempt-scoped ownership to object storage transitions.

Revision ID: 0006_storage_attempt_ownership
Revises: 0005_temporal_source_states
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_storage_attempt_ownership"
down_revision: str | None = "0005_temporal_source_states"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "raw_record_objects",
        sa.Column("attempt_token", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("raw_record_objects", "attempt_token")
