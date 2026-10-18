"""Create private, versioned public-problem formulation records.

Revision ID: 0010_public_problem_formulation
Revises: 0009_storage_attempt_lease
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_public_problem_formulation"
down_revision: str | None = "0009_storage_attempt_lease"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

problem_status = postgresql.ENUM(
    "draft", "confirmed", name="problem_status", create_type=False
)
problem_visibility = postgresql.ENUM(
    "private", "shared", "public", name="problem_visibility", create_type=False
)
problem_field = postgresql.ENUM(
    "territory",
    "affected_population_or_service",
    "observed_consequences",
    "perceived_causes",
    "attempted_actions",
    "available_resources",
    "constraints",
    "desired_outcome",
    name="problem_field",
    create_type=False,
)
knowledge_status = postgresql.ENUM(
    "reported_fact", "perception", "unknown", name="knowledge_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    problem_status.create(bind, checkfirst=True)
    problem_visibility.create(bind, checkfirst=True)
    problem_field.create(bind, checkfirst=True)
    knowledge_status.create(bind, checkfirst=True)

    op.create_table(
        "public_problems",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", problem_status, server_default="draft", nullable=False),
        sa.Column(
            "visibility", problem_visibility, server_default="private", nullable=False
        ),
        sa.Column("edit_token_digest", sa.String(length=64), nullable=False),
        sa.Column("current_version_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_event_sequence", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_public_problems_status", "public_problems", ["status"])

    op.create_table(
        "problem_answer_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("problem_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("field", problem_field, nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("knowledge_status", knowledge_status, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["problem_id"], ["public_problems.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("problem_id", "sequence", name="uq_problem_answer_sequence"),
    )
    op.create_index(
        "ix_problem_answer_events_problem_id", "problem_answer_events", ["problem_id"]
    )
    op.create_index("ix_problem_answer_events_field", "problem_answer_events", ["field"])

    op.create_table(
        "problem_context_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("problem_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("structured_summary", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["problem_id"], ["public_problems.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("problem_id", "version", name="uq_problem_context_version"),
    )
    op.create_index(
        "ix_problem_context_versions_problem_id", "problem_context_versions", ["problem_id"]
    )
    op.create_index(
        "ix_problem_context_versions_confirmed_at",
        "problem_context_versions",
        ["confirmed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_problem_context_versions_confirmed_at", table_name="problem_context_versions"
    )
    op.drop_index(
        "ix_problem_context_versions_problem_id", table_name="problem_context_versions"
    )
    op.drop_table("problem_context_versions")
    op.drop_index("ix_problem_answer_events_field", table_name="problem_answer_events")
    op.drop_index("ix_problem_answer_events_problem_id", table_name="problem_answer_events")
    op.drop_table("problem_answer_events")
    op.drop_index("ix_public_problems_status", table_name="public_problems")
    op.drop_table("public_problems")

    bind = op.get_bind()
    knowledge_status.drop(bind, checkfirst=True)
    problem_field.drop(bind, checkfirst=True)
    problem_visibility.drop(bind, checkfirst=True)
    problem_status.drop(bind, checkfirst=True)
