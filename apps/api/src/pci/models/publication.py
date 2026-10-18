import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from pci.models.base import JSON_TYPE, Base, UUIDPrimaryKeyMixin, reject_append_only_change, utc_now
from pci.models.enums import enum_values


class PublicationAction(StrEnum):
    RETURN = "return"
    PUBLISH = "publish"
    SUPERSEDE = "supersede"
    REVOKE = "revoke"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class PublicationDecision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "publication_decisions"

    contribution_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contribution_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action: Mapped[PublicationAction] = mapped_column(
        Enum(PublicationAction, name="publication_action", values_callable=enum_values),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text)
    supervisor_actor_key: Mapped[str] = mapped_column(String(768), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PublicationOutbox(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "publication_outbox"
    __table_args__ = (
        UniqueConstraint("publication_decision_id", name="uq_publication_outbox_decision"),
    )

    publication_decision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publication_decisions.id", ondelete="RESTRICT"), nullable=False
    )
    contribution_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    scientific_contribution_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    action: Mapped[PublicationAction] = mapped_column(
        Enum(PublicationAction, name="publication_action", values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, name="outbox_status", values_callable=enum_values),
        nullable=False,
        default=OutboxStatus.PENDING,
        index=True,
    )
    attempt_token: Mapped[str | None] = mapped_column(String(36))
    attempt_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublishedContribution(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "published_contributions"
    __table_args__ = (
        UniqueConstraint("contribution_version_id", name="uq_published_contributions_version"),
        Index(
            "uq_published_contributions_one_active",
            "scientific_contribution_id",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active = 1"),
        ),
    )

    scientific_contribution_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    contribution_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    production_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    contribution_type: Mapped[str | None] = mapped_column(String(64), index=True)
    scientific_values: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    approved_groundings: Mapped[list[dict[str, object]]] = mapped_column(JSON_TYPE, nullable=False)
    institution: Mapped[str | None] = mapped_column(String(255), index=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, index=True)
    source_scope: Mapped[str | None] = mapped_column(String(32), index=True)
    production_type: Mapped[str | None] = mapped_column(String(64), index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    source_warning: Mapped[str | None] = mapped_column(Text)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


event.listen(PublicationDecision, "before_update", reject_append_only_change)
event.listen(PublicationDecision, "before_delete", reject_append_only_change)
