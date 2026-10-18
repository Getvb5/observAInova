import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.models.publication import PublishedContribution


def active_projection(session: Session, contribution_id: uuid.UUID) -> PublishedContribution | None:
    return session.scalar(
        select(PublishedContribution).where(
            PublishedContribution.scientific_contribution_id == contribution_id,
            PublishedContribution.active.is_(True),
        )
    )
