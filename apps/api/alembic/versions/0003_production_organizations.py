"""Link productions to their explicitly supplied institutions.

Revision ID: 0003_production_organizations
Revises: 0002_duplicate_candidates
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_production_organizations"
down_revision: str | None = "0002_duplicate_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "production_organizations",
        sa.Column("production_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["production_id"], ["productions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("production_id", "organization_id"),
    )


def downgrade() -> None:
    op.drop_table("production_organizations")
