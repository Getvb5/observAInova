"""Create curated versioned scientific contributions.

Revision ID: 0014_scientific_contributions
Revises: 0013_review_sampling
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_scientific_contributions"
down_revision: str | None = "0013_review_sampling"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

field_decision_action = postgresql.ENUM("accept", "correct", "reject", "insufficient", name="field_decision_action", create_type=False)
contribution_version_status = postgresql.ENUM("draft", "validated", "publication_pending", "published", "superseded", "revoked", name="contribution_version_status", create_type=False)
contribution_type = postgresql.ENUM(name="contribution_type", create_type=False)
contribution_field = postgresql.ENUM(name="contribution_field", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    field_decision_action.create(bind, checkfirst=True)
    contribution_version_status.create(bind, checkfirst=True)
    op.add_column("review_cases", sa.Column("candidate_ids", postgresql.JSONB(astext_type=sa.Text())))
    op.execute("UPDATE review_cases SET candidate_ids = jsonb_build_array(candidate_contribution_id::text) WHERE candidate_contribution_id IS NOT NULL")
    op.create_table(
        "scientific_contributions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_version_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["production_id"], ["productions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scientific_contributions_production_id", "scientific_contributions", ["production_id"])
    columns = [
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scientific_contribution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", contribution_version_status, server_default="draft", nullable=False),
        sa.Column("review_case_id", postgresql.UUID(as_uuid=True)),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_by", sa.String(length=768), nullable=False),
        sa.Column("problem_or_phenomenon", sa.Text()),
        sa.Column("contribution_type", contribution_type),
    ]
    columns.extend(sa.Column(name, sa.Text()) for name in (
        "description", "mechanism", "population", "service", "territory", "methodology",
        "evidence_results", "barriers_limitations", "applicability", "required_resources",
        "maturity", "risks_contraindications",
    ))
    columns.extend([
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["scientific_contribution_id"], ["scientific_contributions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["review_case_id"], ["review_cases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_version_id"], ["contribution_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scientific_contribution_id", "version", name="uq_contribution_versions_contribution_version"),
    ])
    op.create_table("contribution_versions", *columns)
    op.create_index("ix_contribution_versions_scientific_contribution_id", "contribution_versions", ["scientific_contribution_id"])
    op.create_index("ix_contribution_versions_status", "contribution_versions", ["status"])
    op.create_index("ix_contribution_versions_review_case_id", "contribution_versions", ["review_case_id"])
    op.create_table(
        "review_field_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field", contribution_field, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action", field_decision_action, nullable=False),
        sa.Column("value", sa.Text()),
        sa.Column("grounding_ids", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("reason", sa.Text()),
        sa.Column("actor_key", sa.String(length=768), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["review_assignment_id"], ["review_assignments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_assignment_id", "field", "sequence", name="uq_review_field_decision_sequence"),
    )
    op.create_index("ix_review_field_decisions_review_assignment_id", "review_field_decisions", ["review_assignment_id"])
    op.create_index("ix_review_field_decisions_field", "review_field_decisions", ["field"])
    op.create_table(
        "contribution_candidate_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contribution_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_contribution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("curator_actor_key", sa.String(length=768), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contribution_version_id"], ["contribution_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contribution_version_id", "candidate_contribution_id", "review_assignment_id", name="uq_contribution_candidate_sources_identity"),
    )
    op.create_index("ix_contribution_candidate_sources_contribution_version_id", "contribution_candidate_sources", ["contribution_version_id"])
    op.create_table(
        "contribution_groundings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contribution_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field", contribution_field, nullable=False),
        sa.Column("source_scope", sa.String(length=32), nullable=False),
        sa.Column("document_text_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("section", sa.String(length=255)),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contribution_version_id"], ["contribution_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_text_version_id"], ["document_text_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contribution_groundings_contribution_version_id", "contribution_groundings", ["contribution_version_id"])
    op.create_foreign_key("fk_review_cases_published_contribution_version", "review_cases", "contribution_versions", ["published_contribution_version_id"], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    op.drop_constraint("fk_review_cases_published_contribution_version", "review_cases", type_="foreignkey")
    op.drop_index("ix_contribution_groundings_contribution_version_id", table_name="contribution_groundings")
    op.drop_table("contribution_groundings")
    op.drop_index("ix_contribution_candidate_sources_contribution_version_id", table_name="contribution_candidate_sources")
    op.drop_table("contribution_candidate_sources")
    op.drop_index("ix_review_field_decisions_field", table_name="review_field_decisions")
    op.drop_index("ix_review_field_decisions_review_assignment_id", table_name="review_field_decisions")
    op.drop_table("review_field_decisions")
    op.drop_index("ix_contribution_versions_review_case_id", table_name="contribution_versions")
    op.drop_index("ix_contribution_versions_status", table_name="contribution_versions")
    op.drop_index("ix_contribution_versions_scientific_contribution_id", table_name="contribution_versions")
    op.drop_table("contribution_versions")
    op.drop_index("ix_scientific_contributions_production_id", table_name="scientific_contributions")
    op.drop_table("scientific_contributions")
    op.drop_column("review_cases", "candidate_ids")
    bind = op.get_bind()
    contribution_version_status.drop(bind, checkfirst=True)
    field_decision_action.drop(bind, checkfirst=True)
