"""Add conservative duplicate-review state and raw normalization identity.

Revision ID: 0002_duplicate_candidates
Revises: 0001_core_metadata
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_duplicate_candidates"
down_revision: str | None = "0001_core_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("production_versions", sa.Column("publication_year", sa.Integer(), nullable=True))
    op.create_unique_constraint(
        "uq_production_versions_raw_record", "production_versions", ["raw_record_id"]
    )
    op.create_table(
        "duplicate_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "candidate_production_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("reviewer", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected')",
            name="ck_duplicate_candidates_status",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_production_id"], ["productions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["production_id"], ["productions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "production_id",
            "candidate_production_id",
            name="uq_duplicate_candidates_production_candidate",
        ),
    )


def downgrade() -> None:
    op.drop_table("duplicate_candidates")
    op.drop_constraint(
        "uq_production_versions_raw_record", "production_versions", type_="unique"
    )
    op.drop_column("production_versions", "publication_year")
