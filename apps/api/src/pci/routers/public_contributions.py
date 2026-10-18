import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from pci.api_dependencies import SessionDependency
from pci.models.contributions import ContributionGrounding
from pci.models.documents import DocumentTextVersion
from pci.models.production import ProductionVersion
from pci.models.provenance import RawRecord
from pci.models.publication import PublishedContribution
from pci.publication.schemas import PublicContribution, PublicContributionPage

router = APIRouter(prefix="/contributions", tags=["scientific-contributions"])
Page = Annotated[int, Query(ge=1, le=1_000_000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("", response_model=PublicContributionPage, response_model_exclude_none=True)
def list_contributions(
    session: SessionDependency,
    contribution_type: str | None = None,
    institution: str | None = None,
    publication_year: int | None = None,
    source_scope: str | None = None,
    production_type: str | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> dict[str, object]:
    query = select(PublishedContribution).where(PublishedContribution.active.is_(True))
    for column, value in (
        (PublishedContribution.contribution_type, contribution_type),
        (PublishedContribution.institution, institution),
        (PublishedContribution.publication_year, publication_year),
        (PublishedContribution.source_scope, source_scope),
        (PublishedContribution.production_type, production_type),
    ):
        if value is not None:
            query = query.where(column == value)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = session.scalars(
        query.order_by(PublishedContribution.published_at.desc(), PublishedContribution.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_public_contribution(session, item) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get(
    "/{contribution_id}",
    response_model=PublicContribution,
    response_model_exclude_none=True,
)
def contribution_detail(
    contribution_id: uuid.UUID, session: SessionDependency
) -> PublicContribution:
    item = session.scalar(
        select(PublishedContribution).where(
            PublishedContribution.scientific_contribution_id == contribution_id,
            PublishedContribution.active.is_(True),
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Contribution not found")
    return _public_contribution(session, item)


def _public_contribution(
    session: SessionDependency, item: PublishedContribution
) -> PublicContribution:
    production_version = session.scalar(
        select(ProductionVersion)
        .join(
            DocumentTextVersion,
            DocumentTextVersion.production_version_id == ProductionVersion.id,
        )
        .join(
            ContributionGrounding,
            ContributionGrounding.document_text_version_id == DocumentTextVersion.id,
        )
        .where(ContributionGrounding.contribution_version_id == item.contribution_version_id)
        .order_by(ProductionVersion.version, ProductionVersion.id)
        .limit(1)
    )
    original_url = None
    if production_version is not None and production_version.raw_record_id is not None:
        raw = session.get(RawRecord, production_version.raw_record_id)
        original_url = raw.source_url if raw is not None else None
    return PublicContribution.model_validate(item).model_copy(update={"original_url": original_url})
