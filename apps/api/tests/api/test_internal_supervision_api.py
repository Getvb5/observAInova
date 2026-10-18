import uuid

from sqlalchemy.orm import Session

from pci.models.contributions import (
    ContributionVersion,
    ContributionVersionStatus,
    ScientificContribution,
)
from pci.models.production import Production
from pci.models.publication import PublishedContribution

from .test_internal_review_api import internal_client, token


def test_curator_cannot_read_publication_queue(session: Session) -> None:
    response = internal_client(session).get(
        "/api/v1/internal/publication-queue",
        headers={"Authorization": f"Bearer {token('curator')}"},
    )

    assert response.status_code == 403


def test_supervisor_publication_queue_has_no_candidate_payload(session: Session) -> None:
    response = internal_client(session).get(
        "/api/v1/internal/publication-queue",
        headers={"Authorization": f"Bearer {token('supervisor')}"},
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}
    assert "raw_response" not in response.text


def test_dashboard_accepts_either_central_team_role(session: Session) -> None:
    for role in ("curator", "supervisor", "admin"):
        response = internal_client(session).get(
            "/api/v1/internal/dashboard",
            headers={"Authorization": f"Bearer {token(role)}"},
        )
        assert response.status_code == 200


def test_warned_published_contribution_is_actionable_in_supervision_queue(
    session: Session,
) -> None:
    production = Production(canonical_key=f"local:{uuid.uuid4()}")
    session.add(production)
    session.flush()
    contribution = ScientificContribution(production_id=production.id, current_version_number=1)
    session.add(contribution)
    session.flush()
    version = ContributionVersion(
        scientific_contribution_id=contribution.id,
        version=1,
        status=ContributionVersionStatus.PUBLISHED,
        created_by="test|curator",
        description="Solução validada",
    )
    session.add(version)
    session.flush()
    session.add(
        PublishedContribution(
            scientific_contribution_id=contribution.id,
            contribution_version_id=version.id,
            production_id=production.id,
            version=1,
            scientific_values={"description": "Solução validada"},
            approved_groundings=[],
            source_warning="A fonte possui uma versão mais recente.",
            active=True,
        )
    )
    session.flush()
    client = internal_client(session)
    headers = {"Authorization": f"Bearer {token('supervisor')}"}

    queue = client.get("/api/v1/internal/publication-queue", headers=headers)
    detail = client.get(f"/api/v1/internal/contribution-versions/{version.id}", headers=headers)

    assert queue.status_code == 200
    assert [item["id"] for item in queue.json()["items"]] == [str(version.id)]
    assert detail.status_code == 200
    assert detail.json()["source_warning"] == "A fonte possui uma versão mais recente."
