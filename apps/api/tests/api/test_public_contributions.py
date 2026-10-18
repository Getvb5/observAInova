import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pci.main import create_app
from pci.models.publication import PublishedContribution


def test_public_detail_contains_no_private_candidate_fields(session: Session) -> None:
    projection = PublishedContribution(
        scientific_contribution_id=uuid.uuid4(),
        contribution_version_id=uuid.uuid4(),
        production_id=uuid.uuid4(),
        version=1,
        contribution_type="intervention",
        scientific_values={"description": "Solução validada"},
        approved_groundings=[],
        institution="UFPE",
        publication_year=2024,
        source_scope="full_text",
        production_type="thesis",
        active=True,
    )
    session.add(projection)
    session.flush()
    app = create_app()
    app.state.session_factory = lambda: session

    with TestClient(app) as client:
        response = client.get(f"/api/v1/contributions/{projection.scientific_contribution_id}")

    assert response.status_code == 200
    assert response.json()["scientific_values"] == {"description": "Solução validada"}
    for private_field in ("confidence", "provider_response", "review_notes", "raw_response"):
        assert private_field not in response.text
