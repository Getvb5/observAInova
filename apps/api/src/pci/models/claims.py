import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from pci.claims.enums import (
    CandidateStatus,
    ContributionField,
    ContributionType,
    ExtractionRunStatus,
)
from pci.models.base import (
    JSON_TYPE,
    Base,
    UUIDPrimaryKeyMixin,
    reject_append_only_change,
    utc_now,
)
from pci.models.enums import enum_values


class ExtractionRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        UniqueConstraint("supersedes_id", name="uq_extraction_runs_supersedes"),
    )

    document_text_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_text_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    instruction_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ExtractionRunStatus] = mapped_column(
        Enum(
            ExtractionRunStatus,
            name="extraction_run_status",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
        default=ExtractionRunStatus.QUEUED,
        index=True,
    )
    parameters: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE)
    raw_response: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE)
    error_code: Mapped[str | None] = mapped_column(String(100))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CandidateContribution(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "candidate_contributions"
    __table_args__ = (
        UniqueConstraint(
            "extraction_run_id", "ordinal", name="uq_candidate_contributions_run_ordinal"
        ),
        CheckConstraint("ordinal >= 1", name="ck_candidate_contributions_ordinal"),
    )

    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CandidateStatus] = mapped_column(
        Enum(
            CandidateStatus,
            name="candidate_status",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
        default=CandidateStatus.GENERATED,
        index=True,
    )
    suggested_type: Mapped[ContributionType | None] = mapped_column(
        Enum(
            ContributionType,
            name="contribution_type",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class CandidateClaim(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "candidate_claims"
    __table_args__ = (
        UniqueConstraint(
            "candidate_contribution_id",
            "ordinal",
            name="uq_candidate_claims_contribution_ordinal",
        ),
        CheckConstraint("ordinal >= 1", name="ck_candidate_claims_ordinal"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_candidate_claims_confidence"),
    )

    candidate_contribution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_contributions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
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
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class CandidateGrounding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "candidate_groundings"
    __table_args__ = (
        CheckConstraint("page_number IS NULL OR page_number >= 1", name="ck_candidate_groundings_page"),
        CheckConstraint("start_offset >= 0", name="ck_candidate_groundings_start"),
        CheckConstraint("end_offset > start_offset", name="ck_candidate_groundings_offsets"),
    )

    candidate_claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_text_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_text_versions.id", ondelete="RESTRICT"), nullable=False, index=True
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


for model in (CandidateClaim, CandidateGrounding):
    event.listen(model, "before_update", reject_append_only_change)
    event.listen(model, "before_delete", reject_append_only_change)
