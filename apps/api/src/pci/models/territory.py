import uuid

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from pci.models.base import Base
from pci.models.enums import TerritoryRelation, enum_values


class Territory(Base):
    __tablename__ = "territories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class ProductionTerritory(Base):
    __tablename__ = "production_territories"

    production_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("productions.id", ondelete="CASCADE"), primary_key=True
    )
    territory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("territories.id", ondelete="CASCADE"), primary_key=True
    )
    relation: Mapped[TerritoryRelation] = mapped_column(
        Enum(
            TerritoryRelation,
            name="territory_relation",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        primary_key=True,
    )
