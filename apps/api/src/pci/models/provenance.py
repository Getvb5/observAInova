import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
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
from pci.models.enums import HarvestStatus, RightsPolicy, enum_values


class Source(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sources"

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(2048))
    rights_policy: Mapped[RightsPolicy] = mapped_column(
        Enum(
            RightsPolicy,
            name="rights_policy",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schedule: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)

    harvest_runs: Mapped[list["HarvestRun"]] = relationship(back_populates="source")
    raw_records: Mapped[list["RawRecord"]] = relationship(back_populates="source")


class HarvestRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "harvest_runs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[str | None] = mapped_column(Text)
    status: Mapped[HarvestStatus] = mapped_column(
        Enum(
            HarvestStatus,
            name="harvest_status",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
        default=HarvestStatus.RUNNING,
    )
    received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="harvest_runs")
    raw_records: Mapped[list["RawRecord"]] = relationship(back_populates="harvest_run")
    observations: Mapped[list["HarvestObservation"]] = relationship(back_populates="harvest_run")


class RawRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "raw_records"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "source_identifier",
            "state_sequence",
            name="uq_raw_records_source_identifier_state_sequence",
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    source_identifier: Mapped[str] = mapped_column(String(1024), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    state_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    rights_snapshot: Mapped[str | None] = mapped_column(Text)
    is_tombstone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    harvest_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("harvest_runs.id", ondelete="SET NULL")
    )

    source: Mapped[Source] = relationship(back_populates="raw_records")
    harvest_run: Mapped[HarvestRun | None] = relationship(back_populates="raw_records")
    stored_object: Mapped["RawRecordObject | None"] = relationship(
        back_populates="raw_record", uselist=False
    )
    harvest_observations: Mapped[list["HarvestObservation"]] = relationship(
        back_populates="raw_record"
    )


class HarvestObservation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "harvest_observations"
    __table_args__ = (
        UniqueConstraint(
            "harvest_run_id",
            "raw_record_id",
            name="uq_harvest_observations_run_raw_record",
        ),
        UniqueConstraint(
            "harvest_run_id",
            "position",
            name="uq_harvest_observations_run_position",
        ),
    )

    harvest_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("harvest_runs.id", ondelete="RESTRICT"), nullable=False
    )
    raw_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_records.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    harvest_run: Mapped[HarvestRun] = relationship(back_populates="observations")
    raw_record: Mapped[RawRecord] = relationship(back_populates="harvest_observations")


class RawRecordObject(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "raw_record_objects"
    __table_args__ = (
        UniqueConstraint("raw_record_id", name="uq_raw_record_objects_raw_record"),
        UniqueConstraint("object_key", name="uq_raw_record_objects_object_key"),
        CheckConstraint(
            "status IN ('pending', 'stored', 'failed')",
            name="ck_raw_record_objects_status",
        ),
    )

    raw_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_records.id", ondelete="RESTRICT"), nullable=False
    )
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    rights_snapshot: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempt_token: Mapped[str | None] = mapped_column(String(36))
    attempt_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    stored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    raw_record: Mapped[RawRecord] = relationship(back_populates="stored_object")


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"

    actor: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    reason: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


event.listen(RawRecord, "before_update", reject_append_only_change)
event.listen(RawRecord, "before_delete", reject_append_only_change)
event.listen(HarvestObservation, "before_update", reject_append_only_change)
event.listen(HarvestObservation, "before_delete", reject_append_only_change)
