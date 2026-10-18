"""Add stratified sampling and independent review assignments.

Revision ID: 0013_review_sampling
Revises: 0012_candidate_extractions
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_review_sampling"
down_revision: str | None = "0012_candidate_extractions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

sample_split = postgresql.ENUM("calibration", "test", "operations", name="sample_split", create_type=False)
review_case_kind = postgresql.ENUM("candidate", "source_revalidation", name="review_case_kind", create_type=False)
review_lane = postgresql.ENUM("single", "primary", "secondary", "adjudication", name="review_lane", create_type=False)
review_status = postgresql.ENUM("pending", "assigned", "in_review", "completed", "cancelled", name="review_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    sample_split.create(bind, checkfirst=True)
    review_case_kind.create(bind, checkfirst=True)
    review_lane.create(bind, checkfirst=True)
    review_status.create(bind, checkfirst=True)
    op.create_table(
        "sampling_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_size", sa.Integer(), nullable=False),
        sa.Column("selected_size", sa.Integer(), nullable=False),
        sa.Column("test_fraction", sa.String(length=32), nullable=False),
        sa.Column("double_code_fraction", sa.String(length=32), nullable=False),
        sa.Column("seed", sa.String(length=255), nullable=False),
        sa.Column("rule_version", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "review_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sampling_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", review_case_kind, nullable=False),
        sa.Column("candidate_contribution_id", postgresql.UUID(as_uuid=True)),
        sa.Column("published_contribution_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("stratum", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("split", sample_split, nullable=False),
        sa.Column("priority_reason", sa.Text(), nullable=False),
        sa.Column("selection_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(kind = 'candidate' AND candidate_contribution_id IS NOT NULL AND published_contribution_version_id IS NULL) OR (kind = 'source_revalidation' AND candidate_contribution_id IS NULL AND published_contribution_version_id IS NOT NULL)", name="ck_review_cases_exactly_one_target"),
        sa.ForeignKeyConstraint(["sampling_run_id"], ["sampling_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_contribution_id"], ["candidate_contributions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sampling_run_id", "candidate_contribution_id", name="uq_review_cases_sampling_candidate"),
    )
    op.create_index("ix_review_cases_sampling_run_id", "review_cases", ["sampling_run_id"])
    op.create_index("ix_review_cases_candidate_contribution_id", "review_cases", ["candidate_contribution_id"])
    op.create_index("ix_review_cases_published_contribution_version_id", "review_cases", ["published_contribution_version_id"])
    op.create_index("ix_review_cases_split", "review_cases", ["split"])
    op.create_table(
        "review_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lane", review_lane, nullable=False),
        sa.Column("status", review_status, server_default="pending", nullable=False),
        sa.Column("actor_key", sa.String(length=768)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["review_case_id"], ["review_cases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_case_id", "lane", name="uq_review_assignments_case_lane"),
    )
    op.create_index("ix_review_assignments_review_case_id", "review_assignments", ["review_case_id"])
    op.create_index("ix_review_assignments_status", "review_assignments", ["status"])
    op.create_index("ix_review_assignments_actor_key", "review_assignments", ["actor_key"])


def downgrade() -> None:
    op.drop_index("ix_review_assignments_actor_key", table_name="review_assignments")
    op.drop_index("ix_review_assignments_status", table_name="review_assignments")
    op.drop_index("ix_review_assignments_review_case_id", table_name="review_assignments")
    op.drop_table("review_assignments")
    op.drop_index("ix_review_cases_split", table_name="review_cases")
    op.drop_index("ix_review_cases_published_contribution_version_id", table_name="review_cases")
    op.drop_index("ix_review_cases_candidate_contribution_id", table_name="review_cases")
    op.drop_index("ix_review_cases_sampling_run_id", table_name="review_cases")
    op.drop_table("review_cases")
    op.drop_table("sampling_runs")
    bind = op.get_bind()
    review_status.drop(bind, checkfirst=True)
    review_lane.drop(bind, checkfirst=True)
    review_case_kind.drop(bind, checkfirst=True)
    sample_split.drop(bind, checkfirst=True)
