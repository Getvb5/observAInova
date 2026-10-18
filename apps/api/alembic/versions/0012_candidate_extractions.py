"""Create private grounded candidate extractions.

Revision ID: 0012_candidate_extractions
Revises: 0011_document_intelligence
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_candidate_extractions"
down_revision: str | None = "0011_document_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

contribution_field = postgresql.ENUM(
    "problem_or_phenomenon", "contribution_type", "description", "mechanism",
    "population", "service", "territory", "methodology", "evidence_results",
    "barriers_limitations", "applicability", "required_resources", "maturity",
    "risks_contraindications", name="contribution_field", create_type=False,
)
contribution_type = postgresql.ENUM(
    "diagnosis", "causal_explanation", "method", "intervention", "technology",
    "model", "protocol", "recommendation", "evaluation", "instrument",
    name="contribution_type", create_type=False,
)
extraction_run_status = postgresql.ENUM(
    "queued", "running", "succeeded", "failed", "superseded",
    name="extraction_run_status", create_type=False,
)
candidate_status = postgresql.ENUM(
    "generated", "in_review", "accepted", "rejected", "superseded",
    name="candidate_status", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    contribution_field.create(bind, checkfirst=True)
    contribution_type.create(bind, checkfirst=True)
    extraction_run_status.create(bind, checkfirst=True)
    candidate_status.create(bind, checkfirst=True)
    op.create_table(
        "extraction_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_text_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_checksum", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=100), nullable=False),
        sa.Column("instruction_version", sa.String(length=100), nullable=False),
        sa.Column("status", extraction_run_status, server_default="queued", nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["document_text_version_id"], ["document_text_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["extraction_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supersedes_id", name="uq_extraction_runs_supersedes"),
    )
    op.create_index("ix_extraction_runs_document_text_version_id", "extraction_runs", ["document_text_version_id"])
    op.create_index("ix_extraction_runs_document_checksum", "extraction_runs", ["document_checksum"])
    op.create_index("ix_extraction_runs_status", "extraction_runs", ["status"])
    op.create_table(
        "candidate_contributions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", candidate_status, server_default="generated", nullable=False),
        sa.Column("suggested_type", contribution_type),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("ordinal >= 1", name="ck_candidate_contributions_ordinal"),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["extraction_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("extraction_run_id", "ordinal", name="uq_candidate_contributions_run_ordinal"),
    )
    op.create_index("ix_candidate_contributions_extraction_run_id", "candidate_contributions", ["extraction_run_id"])
    op.create_index("ix_candidate_contributions_status", "candidate_contributions", ["status"])
    op.create_table(
        "candidate_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_contribution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("field", contribution_field, nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("ordinal >= 1", name="ck_candidate_claims_ordinal"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_candidate_claims_confidence"),
        sa.ForeignKeyConstraint(["candidate_contribution_id"], ["candidate_contributions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_contribution_id", "ordinal", name="uq_candidate_claims_contribution_ordinal"),
    )
    op.create_index("ix_candidate_claims_candidate_contribution_id", "candidate_claims", ["candidate_contribution_id"])
    op.create_index("ix_candidate_claims_field", "candidate_claims", ["field"])
    op.create_table(
        "candidate_groundings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_text_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("section", sa.String(length=255)),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("page_number IS NULL OR page_number >= 1", name="ck_candidate_groundings_page"),
        sa.CheckConstraint("start_offset >= 0", name="ck_candidate_groundings_start"),
        sa.CheckConstraint("end_offset > start_offset", name="ck_candidate_groundings_offsets"),
        sa.ForeignKeyConstraint(["candidate_claim_id"], ["candidate_claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_text_version_id"], ["document_text_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_groundings_candidate_claim_id", "candidate_groundings", ["candidate_claim_id"])
    op.create_index("ix_candidate_groundings_document_text_version_id", "candidate_groundings", ["document_text_version_id"])
    op.execute("CREATE TRIGGER candidate_claims_append_only BEFORE UPDATE OR DELETE ON candidate_claims FOR EACH ROW EXECUTE FUNCTION prevent_append_only_change()")
    op.execute("CREATE TRIGGER candidate_groundings_append_only BEFORE UPDATE OR DELETE ON candidate_groundings FOR EACH ROW EXECUTE FUNCTION prevent_append_only_change()")


def downgrade() -> None:
    op.execute("DROP TRIGGER candidate_groundings_append_only ON candidate_groundings")
    op.execute("DROP TRIGGER candidate_claims_append_only ON candidate_claims")
    op.drop_index("ix_candidate_groundings_document_text_version_id", table_name="candidate_groundings")
    op.drop_index("ix_candidate_groundings_candidate_claim_id", table_name="candidate_groundings")
    op.drop_table("candidate_groundings")
    op.drop_index("ix_candidate_claims_field", table_name="candidate_claims")
    op.drop_index("ix_candidate_claims_candidate_contribution_id", table_name="candidate_claims")
    op.drop_table("candidate_claims")
    op.drop_index("ix_candidate_contributions_status", table_name="candidate_contributions")
    op.drop_index("ix_candidate_contributions_extraction_run_id", table_name="candidate_contributions")
    op.drop_table("candidate_contributions")
    op.drop_index("ix_extraction_runs_status", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_document_checksum", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_document_text_version_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")
    bind = op.get_bind()
    candidate_status.drop(bind, checkfirst=True)
    extraction_run_status.drop(bind, checkfirst=True)
    contribution_type.drop(bind, checkfirst=True)
    contribution_field.drop(bind, checkfirst=True)
