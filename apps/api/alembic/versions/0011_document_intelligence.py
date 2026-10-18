"""Add academic metadata and immutable document text.

Revision ID: 0011_document_intelligence
Revises: 0010_public_problem_formulation
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_document_intelligence"
down_revision: str | None = "0010_public_problem_formulation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

source_document_status = postgresql.ENUM(
    "pending",
    "retrieved",
    "text_extracted",
    "ocr_required",
    "restricted",
    "failed",
    "superseded",
    name="source_document_status",
    create_type=False,
)
document_text_scope = postgresql.ENUM(
    "full_text", "abstract_only", name="document_text_scope", create_type=False
)
text_extraction_method = postgresql.ENUM(
    "pypdf",
    "metadata_abstract",
    "manual",
    "ocr",
    name="text_extraction_method",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    source_document_status.create(bind, checkfirst=True)
    document_text_scope.create(bind, checkfirst=True)
    text_extraction_method.create(bind, checkfirst=True)

    op.add_column("production_versions", sa.Column("academic_program", sa.Text()))
    op.add_column(
        "production_versions",
        sa.Column("knowledge_areas", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.create_table(
        "source_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status", server_default="pending", type_=source_document_status, nullable=False
        ),
        sa.Column("official_url", sa.String(length=2048)),
        sa.Column("same_origin_host", sa.String(length=255)),
        sa.Column("object_key", sa.String(length=1024)),
        sa.Column("object_checksum", sa.String(length=64)),
        sa.Column("media_type", sa.String(length=255)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("rights_snapshot", sa.Text()),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0", name="ck_source_documents_size"
        ),
        sa.ForeignKeyConstraint(
            ["production_version_id"], ["production_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["source_documents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_source_documents_object_key"),
        sa.UniqueConstraint("supersedes_id", name="uq_source_documents_supersedes"),
    )
    op.create_index(
        "ix_source_documents_production_version_id",
        "source_documents",
        ["production_version_id"],
    )
    op.create_index("ix_source_documents_status", "source_documents", ["status"])

    op.create_table(
        "document_text_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("scope", document_text_scope, nullable=False),
        sa.Column("extraction_method", text_extraction_method, nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_document_text_versions_version"),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_documents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["production_version_id"], ["production_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "production_version_id",
            "version",
            name="uq_document_text_versions_production_version",
        ),
    )
    op.create_index(
        "ix_document_text_versions_source_document_id",
        "document_text_versions",
        ["source_document_id"],
    )
    op.create_index(
        "ix_document_text_versions_production_version_id",
        "document_text_versions",
        ["production_version_id"],
    )

    op.create_table(
        "document_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_text_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("page_number >= 1", name="ck_document_pages_number"),
        sa.CheckConstraint("start_offset >= 0", name="ck_document_pages_start_offset"),
        sa.CheckConstraint("end_offset >= start_offset", name="ck_document_pages_offsets"),
        sa.ForeignKeyConstraint(
            ["document_text_version_id"], ["document_text_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_text_version_id",
            "page_number",
            name="uq_document_pages_text_version_page",
        ),
    )
    op.create_index(
        "ix_document_pages_document_text_version_id",
        "document_pages",
        ["document_text_version_id"],
    )

    op.execute(
        """
        CREATE TRIGGER document_text_versions_append_only
        BEFORE UPDATE OR DELETE ON document_text_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_append_only_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER document_pages_append_only
        BEFORE UPDATE OR DELETE ON document_pages
        FOR EACH ROW EXECUTE FUNCTION prevent_append_only_change()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER document_pages_append_only ON document_pages")
    op.execute(
        "DROP TRIGGER document_text_versions_append_only ON document_text_versions"
    )
    op.drop_index(
        "ix_document_pages_document_text_version_id", table_name="document_pages"
    )
    op.drop_table("document_pages")
    op.drop_index(
        "ix_document_text_versions_production_version_id",
        table_name="document_text_versions",
    )
    op.drop_index(
        "ix_document_text_versions_source_document_id",
        table_name="document_text_versions",
    )
    op.drop_table("document_text_versions")
    op.drop_index("ix_source_documents_status", table_name="source_documents")
    op.drop_index(
        "ix_source_documents_production_version_id", table_name="source_documents"
    )
    op.drop_table("source_documents")
    op.drop_column("production_versions", "knowledge_areas")
    op.drop_column("production_versions", "academic_program")

    bind = op.get_bind()
    text_extraction_method.drop(bind, checkfirst=True)
    document_text_scope.drop(bind, checkfirst=True)
    source_document_status.drop(bind, checkfirst=True)
