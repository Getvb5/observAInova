import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.models.contributions import ContributionCandidateSource


def curator_actor_keys(session: Session, version_id: uuid.UUID) -> set[str]:
    return set(
        session.scalars(
            select(ContributionCandidateSource.curator_actor_key).where(
                ContributionCandidateSource.contribution_version_id == version_id
            )
        ).all()
    )
