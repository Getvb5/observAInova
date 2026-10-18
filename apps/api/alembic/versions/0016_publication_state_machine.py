"""Enforce monotonic publication state and one active projection.

Revision ID: 0016_publication_state_machine
Revises: 0015_publication_projection
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_publication_state_machine"
down_revision: str | None = "0015_publication_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE contribution_version_status ADD VALUE IF NOT EXISTS 'returned'")
    op.create_index(
        "uq_published_contributions_one_active",
        "published_contributions",
        ["scientific_contribution_id"],
        unique=True,
        postgresql_where=op.inline_literal(True),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_published_contributions_one_active",
        table_name="published_contributions",
    )
    # PostgreSQL enum values cannot be safely removed in place.
