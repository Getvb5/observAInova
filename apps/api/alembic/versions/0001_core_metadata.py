"""Create the canonical provenance and production schema.

Revision ID: 0001_core_metadata
Revises:
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_core_metadata"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

rights_policy = postgresql.ENUM(
    "metadata_only",
    "link_only",
    "open_copy",
    "institution_authorized_copy",
    name="rights_policy",
    create_type=False,
)
harvest_status = postgresql.ENUM(
    "running", "completed", "partial", "failed", name="harvest_status", create_type=False
)
record_visibility = postgresql.ENUM(
    "private", "metadata_public", name="record_visibility", create_type=False
)
production_type = postgresql.ENUM(
    "article",
    "thesis",
    "dissertation",
    "undergraduate_work",
    "book",
    "book_chapter",
    "conference_paper",
    "technical_report",
    "research_project",
    "patent",
    "software",
    "dataset",
    "protocol",
    "method",
    "process",
    "social_technology",
    "educational_product",
    "technical_product",
    "other",
    name="production_type",
    create_type=False,
)
territory_relation = postgresql.ENUM(
    "produced_in_pe", "about_pe", name="territory_relation", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    rights_policy.create(bind, checkfirst=True)
    harvest_status.create(bind, checkfirst=True)
    record_visibility.create(bind, checkfirst=True)
    production_type.create(bind, checkfirst=True)
    territory_relation.create(bind, checkfirst=True)

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("connector_type", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=True),
        sa.Column("rights_policy", rights_policy, nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("schedule", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_sources_code"),
    )
    op.create_table(
        "productions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_key", sa.String(length=1024), nullable=False),
        sa.Column("current_version_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("visibility", record_visibility, server_default="private", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_key", name="uq_productions_canonical_key"),
    )
    op.create_table(
        "people",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("identifiers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("identifiers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "territories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_territories_code"),
    )
    op.create_table(
        "harvest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("status", harvest_status, server_default="running", nullable=False),
        sa.Column("received", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unchanged", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "raw_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_identifier", sa.String(length=1024), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("rights_snapshot", sa.Text(), nullable=True),
        sa.Column("harvest_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["harvest_run_id"], ["harvest_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "source_identifier",
            "checksum",
            name="uq_raw_records_source_identifier_checksum",
        ),
    )
    op.create_table(
        "raw_record_objects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column("rights_snapshot", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'stored', 'failed')",
            name="ck_raw_record_objects_status",
        ),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_raw_record_objects_object_key"),
        sa.UniqueConstraint("raw_record_id", name="uq_raw_record_objects_raw_record"),
    )
    op.create_table(
        "production_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("language", sa.String(length=35), nullable=True),
        sa.Column("type", production_type, nullable=True),
        sa.Column("identifiers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("full_text_available", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("rights", sa.Text(), nullable=True),
        sa.Column("normalization_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["production_id"], ["productions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "production_id", "version", name="uq_production_versions_production_version"
        ),
    )
    op.create_table(
        "authorships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["production_id"], ["productions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "production_id", "person_id", "organization_id", name="uq_authorship_identity"
        ),
    )
    op.create_index(
        "uq_authorship_without_organization",
        "authorships",
        ["production_id", "person_id"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_table(
        "production_territories",
        sa.Column("production_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("territory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation", territory_relation, nullable=False),
        sa.ForeignKeyConstraint(
            ["production_id"], ["productions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["territory_id"], ["territories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("production_id", "territory_id", "relation"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        """
        CREATE FUNCTION prevent_append_only_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER raw_records_append_only
        BEFORE UPDATE OR DELETE ON raw_records
        FOR EACH ROW EXECUTE FUNCTION prevent_append_only_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER production_versions_append_only
        BEFORE UPDATE OR DELETE ON production_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_append_only_change()
        """
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("production_territories")
    op.drop_table("authorships")
    op.drop_table("production_versions")
    op.drop_table("raw_record_objects")
    op.drop_table("raw_records")
    op.drop_table("harvest_runs")
    op.drop_table("territories")
    op.drop_table("organizations")
    op.drop_table("people")
    op.drop_table("productions")
    op.drop_table("sources")
    op.execute("DROP FUNCTION prevent_append_only_change()")

    territory_relation.drop(op.get_bind(), checkfirst=True)
    production_type.drop(op.get_bind(), checkfirst=True)
    record_visibility.drop(op.get_bind(), checkfirst=True)
    harvest_status.drop(op.get_bind(), checkfirst=True)
    rights_policy.drop(op.get_bind(), checkfirst=True)
