"""Add a reclaimable lease timestamp to object storage attempts.

Revision ID: 0009_storage_attempt_lease
Revises: 0008_bounded_catalog_matching
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_storage_attempt_lease"
down_revision: str | None = "0008_bounded_catalog_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "raw_record_objects",
        sa.Column("attempt_started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("raw_record_objects", "attempt_started_at")
