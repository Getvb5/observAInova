import uuid

from sqlalchemy.orm import Session

from pci.contributions.repository import curator_actor_keys
from pci.models.contributions import (
    ContributionCandidateSource,
    ContributionVersion,
    ContributionVersionStatus,
    ScientificContribution,
)
from pci.models.production import Production


def test_version_records_all_curator_sources_for_four_eyes_check(session: Session) -> None:
    production = Production(canonical_key=f"local:{uuid.uuid4()}")
    session.add(production)
    session.flush()
    contribution = ScientificContribution(production_id=production.id)
    session.add(contribution)
    session.flush()
    version = ContributionVersion(
        scientific_contribution_id=contribution.id,
        version=1,
        status=ContributionVersionStatus.VALIDATED,
        created_by="issuer|adjudicator",
    )
    session.add(version)
    session.flush()
    session.add_all(
        [
            ContributionCandidateSource(
                contribution_version_id=version.id,
                candidate_contribution_id=uuid.uuid4(),
                review_assignment_id=uuid.uuid4(),
                curator_actor_key="issuer|curator-one",
            ),
            ContributionCandidateSource(
                contribution_version_id=version.id,
                candidate_contribution_id=uuid.uuid4(),
                review_assignment_id=uuid.uuid4(),
                curator_actor_key="issuer|curator-two",
            ),
        ]
    )
    session.flush()

    assert curator_actor_keys(session, version.id) == {
        "issuer|curator-one",
        "issuer|curator-two",
    }
