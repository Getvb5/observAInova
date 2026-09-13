"""Add indexed candidate keys for bounded catalog matching.

Revision ID: 0008_bounded_catalog_matching
Revises: 0007_bounded_harvest_handoff
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_bounded_catalog_matching"
down_revision: str | None = "0007_bounded_harvest_handoff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column_name in (
        "title_digest",
        "doi_digest",
        "patent_digest",
        "handle_digest",
        "source_digest",
    ):
        op.add_column(
            "production_versions",
            sa.Column(column_name, sa.String(length=32), nullable=True),
        )
    op.add_column("people", sa.Column("name_digest", sa.String(length=32)))
    op.add_column("people", sa.Column("orcid", sa.String(length=19)))
    op.add_column("organizations", sa.Column("name_digest", sa.String(length=32)))

    op.execute("DROP TRIGGER production_versions_append_only ON production_versions")
    op.execute(
        """
        UPDATE production_versions
        SET
            title_digest = md5(lower(regexp_replace(btrim(title), E'\\s+', ' ', 'g'))),
            doi_digest = md5(identifiers ->> 'doi'),
            patent_digest = md5(identifiers ->> 'patent'),
            handle_digest = md5(identifiers ->> 'handle'),
            source_digest = md5(identifiers ->> 'source')
        """
    )
    op.execute(
        """
        CREATE TRIGGER production_versions_append_only
        BEFORE UPDATE OR DELETE ON production_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_append_only_change()
        """
    )
    op.execute(
        """
        UPDATE people
        SET
            name_digest = md5(lower(regexp_replace(btrim(name), E'\\s+', ' ', 'g'))),
            orcid = identifiers ->> 'orcid'
        """
    )
    op.execute(
        """
        UPDATE organizations
        SET name_digest = md5(lower(regexp_replace(btrim(name), E'\\s+', ' ', 'g')))
        """
    )

    for table_name, column_name in (
        ("production_versions", "title_digest"),
        ("production_versions", "doi_digest"),
        ("production_versions", "patent_digest"),
        ("production_versions", "handle_digest"),
        ("production_versions", "source_digest"),
        ("people", "name_digest"),
        ("people", "orcid"),
        ("organizations", "name_digest"),
    ):
        op.create_index(f"ix_{table_name}_{column_name}", table_name, [column_name])


def downgrade() -> None:
    for table_name, column_name in reversed(
        (
            ("production_versions", "title_digest"),
            ("production_versions", "doi_digest"),
            ("production_versions", "patent_digest"),
            ("production_versions", "handle_digest"),
            ("production_versions", "source_digest"),
            ("people", "name_digest"),
            ("people", "orcid"),
            ("organizations", "name_digest"),
        )
    ):
        op.drop_index(f"ix_{table_name}_{column_name}", table_name=table_name)
    op.drop_column("organizations", "name_digest")
    op.drop_column("people", "orcid")
    op.drop_column("people", "name_digest")
    for column_name in (
        "source_digest",
        "handle_digest",
        "patent_digest",
        "doi_digest",
        "title_digest",
    ):
        op.drop_column("production_versions", column_name)
