import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column

from pci.claims.enums import ContributionField, ContributionType
from pci.models.base import JSON_TYPE, Base, UUIDPrimaryKeyMixin, reject_append_only_change, utc_now
from pci.models.enums import enum_values


class FieldDecisionAction(StrEnum):
    ACCEPT = "accept"
    CORRECT = "correct"
    REJECT = "reject"
    INSUFFICIENT = "insufficient"


class ContributionVersionStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    PUBLICATION_PENDING = "publication_pending"
    PUBLISHED = "published"
    RETURNED = "returned"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


class ScientificContribution(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "scientific_contributions"

    production_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("productions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ContributionVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "contribution_versions"
    __table_args__ = (
        UniqueConstraint(
            "scientific_contribution_id",
            "version",
            name="uq_contribution_versions_contribution_version",
        ),
    )

    scientific_contribution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scientific_contributions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ContributionVersionStatus] = mapped_column(
        Enum(
            ContributionVersionStatus,
            name="contribution_version_status",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
        default=ContributionVersionStatus.DRAFT,
        index=True,
        active_history=True,
    )
    review_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_cases.id", ondelete="RESTRICT"), index=True
    )
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contribution_versions.id", ondelete="RESTRICT")
    )
    created_by: Mapped[str] = mapped_column(String(768), nullable=False)
    problem_or_phenomenon: Mapped[str | None] = mapped_column(Text)
    contribution_type: Mapped[ContributionType | None] = mapped_column(
        Enum(
            ContributionType,
            name="contribution_type",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        )
    )
    description: Mapped[str | None] = mapped_column(Text)
    mechanism: Mapped[str | None] = mapped_column(Text)
    population: Mapped[str | None] = mapped_column(Text)
    service: Mapped[str | None] = mapped_column(Text)
    territory: Mapped[str | None] = mapped_column(Text)
    methodology: Mapped[str | None] = mapped_column(Text)
    evidence_results: Mapped[str | None] = mapped_column(Text)
    barriers_limitations: Mapped[str | None] = mapped_column(Text)
    applicability: Mapped[str | None] = mapped_column(Text)
    required_resources: Mapped[str | None] = mapped_column(Text)
    maturity: Mapped[str | None] = mapped_column(Text)
    risks_contraindications: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContributionCandidateSource(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "contribution_candidate_sources"
    __table_args__ = (
        UniqueConstraint(
            "contribution_version_id",
            "candidate_contribution_id",
            "review_assignment_id",
            name="uq_contribution_candidate_sources_identity",
        ),
    )

    contribution_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contribution_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    candidate_contribution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    review_assignment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    curator_actor_key: Mapped[str] = mapped_column(String(768), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ReviewFieldDecision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "review_field_decisions"
    __table_args__ = (
        UniqueConstraint(
            "review_assignment_id", "field", "sequence", name="uq_review_field_decision_sequence"
        ),
    )

    review_assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_assignments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    field: Mapped[ContributionField] = mapped_column(
        Enum(
            ContributionField,
            name="contribution_field",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[FieldDecisionAction] = mapped_column(
        Enum(
            FieldDecisionAction,
            name="field_decision_action",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
    )
    value: Mapped[str | None] = mapped_column(Text)
    grounding_ids: Mapped[list[str] | None] = mapped_column(JSON_TYPE)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_key: Mapped[str] = mapped_column(String(768), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ContributionGrounding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "contribution_groundings"

    contribution_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contribution_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    field: Mapped[ContributionField] = mapped_column(
        Enum(
            ContributionField,
            name="contribution_field",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
    )
    source_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    document_text_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_text_versions.id", ondelete="RESTRICT"), nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(255))
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    quote_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


SCIENTIFIC_COLUMNS = tuple(field.value for field in ContributionField)


def _prevent_validated_scientific_change(
    _: object, __: object, target: ContributionVersion
) -> None:
    state = inspect(target)
    status_history = state.attrs.status.load_history()
    prior_status = status_history.deleted[0] if status_history.deleted else target.status
    if prior_status is ContributionVersionStatus.DRAFT:
        return
    if any(state.attrs[field].history.has_changes() for field in SCIENTIFIC_COLUMNS):
        from pci.contributions.service import ImmutableContributionError

        raise ImmutableContributionError("validated scientific fields are immutable")


event.listen(ContributionVersion, "before_update", _prevent_validated_scientific_change)
event.listen(ContributionGrounding, "before_update", reject_append_only_change)
event.listen(ContributionGrounding, "before_delete", reject_append_only_change)
event.listen(ReviewFieldDecision, "before_update", reject_append_only_change)
event.listen(ReviewFieldDecision, "before_delete", reject_append_only_change)
event.listen(ContributionCandidateSource, "before_update", reject_append_only_change)
event.listen(ContributionCandidateSource, "before_delete", reject_append_only_change)
