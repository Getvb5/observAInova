"""Add an actionable revision target for contributions returned to curation.

Revision ID: 0019_return_correction_workflow
Revises: 0018_governance_integrity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019_return_correction_workflow"
down_revision: str | None = "0018_governance_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL requires a newly added enum value to be committed before it can
    # be referenced by the replacement check constraint below.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE review_case_kind ADD VALUE IF NOT EXISTS 'return_correction'")
    op.add_column(
        "review_cases",
        sa.Column("correction_base_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_review_cases_correction_base_version",
        "review_cases",
        "contribution_versions",
        ["correction_base_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_review_cases_correction_base_version_id",
        "review_cases",
        ["correction_base_version_id"],
    )
    op.create_unique_constraint(
        "uq_review_cases_correction_base_version",
        "review_cases",
        ["correction_base_version_id"],
    )
    op.drop_constraint("ck_review_cases_exactly_one_target", "review_cases", type_="check")
    op.create_check_constraint(
        "ck_review_cases_exactly_one_target",
        "review_cases",
        "(kind = 'candidate' AND candidate_contribution_id IS NOT NULL "
        "AND published_contribution_version_id IS NULL "
        "AND correction_base_version_id IS NULL) OR "
        "(kind = 'source_revalidation' AND candidate_contribution_id IS NULL "
        "AND published_contribution_version_id IS NOT NULL "
        "AND correction_base_version_id IS NULL) OR "
        "(kind = 'return_correction' AND candidate_contribution_id IS NOT NULL "
        "AND published_contribution_version_id IS NULL "
        "AND correction_base_version_id IS NOT NULL)",
    )
    op.execute(
        """
        UPDATE scientific_contributions AS contribution
        SET current_version_number = latest.version
        FROM (
          SELECT scientific_contribution_id, MAX(version) AS version
          FROM contribution_versions
          GROUP BY scientific_contribution_id
        ) AS latest
        WHERE latest.scientific_contribution_id = contribution.id
          AND contribution.current_version_number <> latest.version
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_review_cases_exactly_one_target", "review_cases", type_="check")
    op.create_check_constraint(
        "ck_review_cases_exactly_one_target",
        "review_cases",
        "(kind = 'candidate' AND candidate_contribution_id IS NOT NULL "
        "AND published_contribution_version_id IS NULL) OR "
        "(kind = 'source_revalidation' AND candidate_contribution_id IS NULL "
        "AND published_contribution_version_id IS NOT NULL)",
    )
    op.drop_constraint("uq_review_cases_correction_base_version", "review_cases", type_="unique")
    op.drop_index("ix_review_cases_correction_base_version_id", table_name="review_cases")
    op.drop_constraint(
        "fk_review_cases_correction_base_version", "review_cases", type_="foreignkey"
    )
    op.drop_column("review_cases", "correction_base_version_id")
