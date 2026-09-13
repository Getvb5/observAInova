import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pci.models.base import JSON_TYPE, Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from pci.models.production import Production


class Person(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "people"

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    name_digest: Mapped[str | None] = mapped_column(String(32), index=True)
    orcid: Mapped[str | None] = mapped_column(String(19), index=True)
    identifiers: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)


class Organization(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    name_digest: Mapped[str | None] = mapped_column(String(32), index=True)
    identifiers: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)


class ProductionOrganization(Base):
    """An institution explicitly attached to a production's metadata."""

    __tablename__ = "production_organizations"

    production_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("productions.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), primary_key=True
    )

    production: Mapped["Production"] = relationship()
    organization: Mapped[Organization] = relationship()


class Authorship(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "authorships"
    __table_args__ = (
        UniqueConstraint(
            "production_id", "person_id", "organization_id", name="uq_authorship_identity"
        ),
        Index(
            "uq_authorship_without_organization",
            "production_id",
            "person_id",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
            sqlite_where=text("organization_id IS NULL"),
        ),
    )

    production_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("productions.id", ondelete="CASCADE"), nullable=False
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("people.id", ondelete="RESTRICT"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    production: Mapped["Production"] = relationship()
    person: Mapped[Person] = relationship()
    organization: Mapped[Organization | None] = relationship()
