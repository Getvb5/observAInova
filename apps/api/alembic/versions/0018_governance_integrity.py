"""Enforce append-only governance evidence and legal version transitions.

Revision ID: 0018_governance_integrity
Revises: 0017_review_case_lineage
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_governance_integrity"
down_revision: str | None = "0017_review_case_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_contribution_candidate_sources_candidate",
        "contribution_candidate_sources",
        "candidate_contributions",
        ["candidate_contribution_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_contribution_candidate_sources_assignment",
        "contribution_candidate_sources",
        "review_assignments",
        ["review_assignment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        """
        CREATE FUNCTION reject_governance_history_change() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in (
        "review_field_decisions",
        "contribution_candidate_sources",
        "contribution_groundings",
        "publication_decisions",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_governance_history_change();
            """
        )
    op.execute(
        """
        CREATE FUNCTION enforce_contribution_version_integrity() RETURNS trigger AS $$
        BEGIN
          IF OLD.status <> 'draft' AND ROW(
            OLD.problem_or_phenomenon, OLD.contribution_type, OLD.description,
            OLD.mechanism, OLD.population, OLD.service, OLD.territory,
            OLD.methodology, OLD.evidence_results, OLD.barriers_limitations,
            OLD.applicability, OLD.required_resources, OLD.maturity,
            OLD.risks_contraindications
          ) IS DISTINCT FROM ROW(
            NEW.problem_or_phenomenon, NEW.contribution_type, NEW.description,
            NEW.mechanism, NEW.population, NEW.service, NEW.territory,
            NEW.methodology, NEW.evidence_results, NEW.barriers_limitations,
            NEW.applicability, NEW.required_resources, NEW.maturity,
            NEW.risks_contraindications
          ) THEN
            RAISE EXCEPTION 'validated scientific fields are immutable';
          END IF;
          IF OLD.status <> NEW.status AND NOT (
            (OLD.status = 'draft' AND NEW.status = 'validated') OR
            (OLD.status = 'validated' AND NEW.status IN ('publication_pending', 'returned')) OR
            (OLD.status = 'publication_pending' AND NEW.status IN ('published', 'validated', 'superseded')) OR
            (OLD.status = 'published' AND NEW.status IN ('superseded', 'revoked'))
          ) THEN
            RAISE EXCEPTION 'illegal contribution version status transition: % -> %', OLD.status, NEW.status;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_contribution_versions_integrity
        BEFORE UPDATE ON contribution_versions
        FOR EACH ROW EXECUTE FUNCTION enforce_contribution_version_integrity();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_contribution_versions_integrity ON contribution_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_contribution_version_integrity()")
    for table in (
        "review_field_decisions",
        "contribution_candidate_sources",
        "contribution_groundings",
        "publication_decisions",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_governance_history_change()")
    op.drop_constraint(
        "fk_contribution_candidate_sources_assignment",
        "contribution_candidate_sources",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_contribution_candidate_sources_candidate",
        "contribution_candidate_sources",
        type_="foreignkey",
    )
