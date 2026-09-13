import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pci.models.base import (
    JSON_TYPE,
    Base,
    UUIDPrimaryKeyMixin,
    reject_append_only_change,
    utc_now,
)
from pci.models.enums import ProductionType, RecordVisibility, enum_values


class Production(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "productions"

    canonical_key: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    visibility: Mapped[RecordVisibility] = mapped_column(
        Enum(
            RecordVisibility,
            name="record_visibility",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
        default=RecordVisibility.PRIVATE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    versions: Mapped[list["ProductionVersion"]] = relationship(
        back_populates="production", passive_deletes="all"
    )


class ProductionVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "production_versions"
    __table_args__ = (
        UniqueConstraint(
            "production_id", "version", name="uq_production_versions_production_version"
        ),
        UniqueConstraint("raw_record_id", name="uq_production_versions_raw_record"),
    )

    production_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("productions.id", ondelete="RESTRICT"), nullable=False
    )
    raw_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("raw_records.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_digest: Mapped[str | None] = mapped_column(String(32), index=True)
    abstract: Mapped[str | None] = mapped_column(Text)
    publication_date: Mapped[date | None] = mapped_column(Date)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(35))
    type: Mapped[ProductionType | None] = mapped_column(
        Enum(
            ProductionType,
            name="production_type",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        )
    )
    identifiers: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    doi_digest: Mapped[str | None] = mapped_column(String(32), index=True)
    patent_digest: Mapped[str | None] = mapped_column(String(32), index=True)
    handle_digest: Mapped[str | None] = mapped_column(String(32), index=True)
    source_digest: Mapped[str | None] = mapped_column(String(32), index=True)
    keywords: Mapped[list[str] | None] = mapped_column(JSON_TYPE)
    publishers: Mapped[list[str] | None] = mapped_column(JSON_TYPE)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    full_text_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rights: Mapped[str | None] = mapped_column(Text)
    normalization_report: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)

    production: Mapped[Production] = relationship(back_populates="versions")


class DuplicateCandidate(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (
        UniqueConstraint(
            "production_id",
            "candidate_production_id",
            name="uq_duplicate_candidates_production_candidate",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected')",
            name="ck_duplicate_candidates_status",
        ),
    )

    production_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("productions.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_production_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("productions.id", ondelete="RESTRICT"), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    reviewer: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


event.listen(ProductionVersion, "before_update", reject_append_only_change)
event.listen(ProductionVersion, "before_delete", reject_append_only_change)
