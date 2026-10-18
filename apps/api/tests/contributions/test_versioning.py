import uuid

import pytest
from sqlalchemy.orm import Session

from pci.claims.enums import ContributionType
from pci.contributions.service import ImmutableContributionError
from pci.models.contributions import (
    ContributionVersion,
    ContributionVersionStatus,
    ScientificContribution,
)
from pci.models.production import Production


def test_validated_scientific_fields_are_immutable(session: Session) -> None:
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
        created_by="issuer|curator",
        problem_or_phenomenon="Filas extensas",
        contribution_type=ContributionType.INTERVENTION,
        description="Intervenção validada",
    )
    session.add(version)
    session.commit()

    version.description = "mudança silenciosa"
    with pytest.raises(ImmutableContributionError):
        session.flush()


def test_draft_scientific_fields_can_be_edited_before_validation(session: Session) -> None:
    production = Production(canonical_key=f"local:{uuid.uuid4()}")
    session.add(production)
    session.flush()
    contribution = ScientificContribution(production_id=production.id)
    session.add(contribution)
    session.flush()
    version = ContributionVersion(
        scientific_contribution_id=contribution.id,
        version=1,
        status=ContributionVersionStatus.DRAFT,
        created_by="issuer|curator",
        description="Rascunho",
    )
    session.add(version)
    session.commit()

    version.description = "Rascunho corrigido"
    session.commit()

    assert version.description == "Rascunho corrigido"


def test_validated_version_cannot_bypass_immutability_by_reverting_status(
    session: Session,
) -> None:
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
        created_by="issuer|curator",
        description="Validada",
    )
    session.add(version)
    session.commit()

    version.status = ContributionVersionStatus.DRAFT
    version.description = "Mutação indevida"
    with pytest.raises(ImmutableContributionError):
        session.flush()
