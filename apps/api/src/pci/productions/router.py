import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from pci.api_dependencies import SessionDependency
from pci.models.enums import ProductionType, TerritoryRelation
from pci.productions.repository import ProductionFilters
from pci.productions.schemas import PublicProductionDetail, PublicProductionPage
from pci.productions.service import (
    get_public_production,
    list_public_productions,
)

router = APIRouter(prefix="/productions", tags=["productions"])
ProductionTypeQuery = Annotated[ProductionType | None, Query(alias="type")]
PageQuery = Annotated[int, Query(ge=1, le=1_000_000)]
PageSizeQuery = Annotated[int, Query(ge=1, le=100)]
PublicationYearQuery = Annotated[int | None, Query(ge=1, le=9999)]


@router.get("", response_model=PublicProductionPage)
def list_productions(
    session: SessionDependency,
    institution: str | None = None,
    production_type: ProductionTypeQuery = None,
    publication_year: PublicationYearQuery = None,
    territory_relation: TerritoryRelation | None = None,
    page: PageQuery = 1,
    page_size: PageSizeQuery = 20,
) -> PublicProductionPage:
    return list_public_productions(
        session,
        ProductionFilters(
            institution=institution,
            production_type=production_type,
            publication_year=publication_year,
            territory_relation=territory_relation,
        ),
        page=page,
        page_size=page_size,
    )


@router.get("/{production_id}", response_model=PublicProductionDetail)
def production_detail(
    production_id: uuid.UUID,
    session: SessionDependency,
) -> PublicProductionDetail:
    production = get_public_production(session, production_id)
    if production is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Production not found",
        )
    return production
