import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pci.models.base import JSON_TYPE, Base, UUIDPrimaryKeyMixin, utc_now
from pci.models.enums import enum_values


class SampleSplit(StrEnum):
    CALIBRATION = "calibration"
    TEST = "test"
    OPERATIONS = "operations"


class ReviewCaseKind(StrEnum):
    CANDIDATE = "candidate"
    SOURCE_REVALIDATION = "source_revalidation"
    RETURN_CORRECTION = "return_correction"


class ReviewLane(StrEnum):
    SINGLE = "single"
    PRIMARY = "primary"
    SECONDARY = "secondary"
    ADJUDICATION = "adjudication"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_REVIEW = "in_review"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SamplingRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sampling_runs"

    target_size: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_size: Mapped[int] = mapped_column(Integer, nullable=False)
    test_fraction: Mapped[str] = mapped_column(String(32), nullable=False)
    double_code_fraction: Mapped[str] = mapped_column(String(32), nullable=False)
    seed: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    cases: Mapped[list["ReviewCase"]] = relationship(
        back_populates="sampling_run", order_by="ReviewCase.selection_order"
    )


class ReviewCase(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "review_cases"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'candidate' AND candidate_contribution_id IS NOT NULL "
            "AND published_contribution_version_id IS NULL "
            "AND correction_base_version_id IS NULL) OR "
            "(kind = 'source_revalidation' AND candidate_contribution_id IS NULL "
            "AND published_contribution_version_id IS NOT NULL "
            "AND correction_base_version_id IS NULL) OR "
            "(kind = 'return_correction' AND candidate_contribution_id IS NOT NULL "
            "AND published_contribution_version_id IS NULL "
            "AND correction_base_version_id IS NOT NULL)",
            name="ck_review_cases_exactly_one_target",
        ),
        UniqueConstraint(
            "correction_base_version_id",
            name="uq_review_cases_correction_base_version",
        ),
    )

    sampling_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sampling_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[ReviewCaseKind] = mapped_column(
        Enum(
            ReviewCaseKind,
            name="review_case_kind",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
    )
    candidate_contribution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_contributions.id", ondelete="RESTRICT"), index=True
    )
    candidate_ids: Mapped[list[str] | None] = mapped_column(JSON_TYPE)
    published_contribution_version_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    # The database migration owns this FK. Keeping it out of SQLAlchemy metadata avoids
    # a circular review_cases <-> contribution_versions dependency in SQLite tests.
    correction_base_version_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    stratum: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    split: Mapped[SampleSplit] = mapped_column(
        Enum(
            SampleSplit,
            name="sample_split",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
        index=True,
    )
    priority_reason: Mapped[str] = mapped_column(Text, nullable=False)
    superseded_by_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_cases.id", ondelete="RESTRICT"), index=True
    )
    selection_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    sampling_run: Mapped[SamplingRun] = relationship(back_populates="cases")
    assignments: Mapped[list["ReviewAssignment"]] = relationship(
        back_populates="review_case", order_by="ReviewAssignment.lane"
    )


class ReviewAssignment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "review_assignments"
    __table_args__ = (
        UniqueConstraint("review_case_id", "lane", name="uq_review_assignments_case_lane"),
    )

    review_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_cases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    lane: Mapped[ReviewLane] = mapped_column(
        Enum(
            ReviewLane,
            name="review_lane",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
    )
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(
            ReviewStatus,
            name="review_status",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
        default=ReviewStatus.PENDING,
        index=True,
    )
    actor_key: Mapped[str | None] = mapped_column(String(768), index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    review_case: Mapped[ReviewCase] = relationship(back_populates="assignments")
