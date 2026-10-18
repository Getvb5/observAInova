import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pci.models.base import (
    JSON_TYPE,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    reject_append_only_change,
    utc_now,
)
from pci.models.enums import enum_values


class ProblemStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class ProblemVisibility(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"
    PUBLIC = "public"


class ProblemField(StrEnum):
    TERRITORY = "territory"
    AFFECTED_POPULATION_OR_SERVICE = "affected_population_or_service"
    OBSERVED_CONSEQUENCES = "observed_consequences"
    PERCEIVED_CAUSES = "perceived_causes"
    ATTEMPTED_ACTIONS = "attempted_actions"
    AVAILABLE_RESOURCES = "available_resources"
    CONSTRAINTS = "constraints"
    DESIRED_OUTCOME = "desired_outcome"


class KnowledgeStatus(StrEnum):
    REPORTED_FACT = "reported_fact"
    PERCEPTION = "perception"
    UNKNOWN = "unknown"


problem_status_type = Enum(
    ProblemStatus,
    name="problem_status",
    values_callable=enum_values,
    validate_strings=True,
    create_constraint=True,
)
problem_visibility_type = Enum(
    ProblemVisibility,
    name="problem_visibility",
    values_callable=enum_values,
    validate_strings=True,
    create_constraint=True,
)
problem_field_type = Enum(
    ProblemField,
    name="problem_field",
    values_callable=enum_values,
    validate_strings=True,
    create_constraint=True,
)
knowledge_status_type = Enum(
    KnowledgeStatus,
    name="knowledge_status",
    values_callable=enum_values,
    validate_strings=True,
    create_constraint=True,
)


class PublicProblem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "public_problems"

    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ProblemStatus] = mapped_column(
        problem_status_type, nullable=False, default=ProblemStatus.DRAFT, index=True
    )
    visibility: Mapped[ProblemVisibility] = mapped_column(
        problem_visibility_type, nullable=False, default=ProblemVisibility.PRIVATE
    )
    edit_token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    answer_events: Mapped[list["ProblemAnswerEvent"]] = relationship(
        back_populates="problem", passive_deletes="all"
    )
    context_versions: Mapped[list["ProblemContextVersion"]] = relationship(
        back_populates="problem", passive_deletes="all"
    )


class ProblemAnswerEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "problem_answer_events"
    __table_args__ = (
        UniqueConstraint("problem_id", "sequence", name="uq_problem_answer_sequence"),
    )

    problem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_problems.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    field: Mapped[ProblemField] = mapped_column(
        problem_field_type, nullable=False, index=True
    )
    value: Mapped[str | None] = mapped_column(Text)
    knowledge_status: Mapped[KnowledgeStatus] = mapped_column(
        knowledge_status_type, nullable=False
    )

    problem: Mapped[PublicProblem] = relationship(back_populates="answer_events")


class ProblemContextVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "problem_context_versions"
    __table_args__ = (
        UniqueConstraint("problem_id", "version", name="uq_problem_context_version"),
    )

    problem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_problems.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    structured_summary: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )

    problem: Mapped[PublicProblem] = relationship(back_populates="context_versions")


for immutable_model in (ProblemAnswerEvent, ProblemContextVersion):
    event.listen(immutable_model, "before_update", reject_append_only_change)
    event.listen(immutable_model, "before_delete", reject_append_only_change)
