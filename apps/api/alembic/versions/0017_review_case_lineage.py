"""Allow explicit split and merge lineage for review cases.

Revision ID: 0017_review_case_lineage
Revises: 0016_publication_state_machine
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_review_case_lineage"
down_revision: str | None = "0016_publication_state_machine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_review_cases_sampling_candidate", "review_cases", type_="unique")
    op.add_column(
        "review_cases",
        sa.Column("superseded_by_case_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "fk_review_cases_superseded_by_case_id",
        "review_cases",
        "review_cases",
        ["superseded_by_case_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_review_cases_superseded_by_case_id",
        "review_cases",
        ["superseded_by_case_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_cases_superseded_by_case_id", table_name="review_cases")
    op.drop_constraint("fk_review_cases_superseded_by_case_id", "review_cases", type_="foreignkey")
    op.drop_column("review_cases", "superseded_by_case_id")
    op.create_unique_constraint(
        "uq_review_cases_sampling_candidate",
        "review_cases",
        ["sampling_run_id", "candidate_contribution_id"],
    )
