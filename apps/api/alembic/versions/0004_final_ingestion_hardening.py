"""Harden immutable ingestion provenance and publisher metadata.

Revision ID: 0004_final_ingestion_hardening
Revises: 0003_production_organizations
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_final_ingestion_hardening"
down_revision: str | None = "0003_production_organizations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "raw_records",
        sa.Column("is_tombstone", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "production_versions",
        sa.Column("publishers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("production_versions", "publishers")
    op.drop_column("raw_records", "is_tombstone")
