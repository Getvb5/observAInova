from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.models.actors import Authorship, Organization
from pci.models.production import Production
from pci.models.provenance import AuditEvent


def test_top_level_institution_is_filterable_without_becoming_author_affiliation(
    client: TestClient,
    session: Session,
    productions: dict[str, Production],
) -> None:
    response = client.get(
        "/api/v1/productions",
        params={"institution": "Universidade Federal de Pernambuco"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    top_level_institution_affiliation = session.scalar(
        select(Authorship)
        .join(Organization, Organization.id == Authorship.organization_id)
        .where(
            Authorship.production_id == productions["public"].id,
            Organization.name == "Universidade Federal de Pernambuco",
        )
    )
    assert top_level_institution_affiliation is None
    assert session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "production_organization.created",
            AuditEvent.entity_id == productions["public"].id,
        )
    ) is not None


def test_public_routes_require_no_authentication(
    client: TestClient, productions: dict[str, Production]
) -> None:
    list_response = client.get("/api/v1/productions")
    detail_response = client.get(f"/api/v1/productions/{productions['public'].id}")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
