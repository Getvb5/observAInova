import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from pci.models.production import Production


def test_public_list_batches_tombstone_state_query(
    client: TestClient,
    session: Session,
    productions: dict[str, Production],
) -> None:
    tombstone_query_count = 0

    def count_tombstone_query(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal tombstone_query_count
        if "FROM raw_records" in statement and "raw_records.is_tombstone" in statement:
            tombstone_query_count += 1

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", count_tombstone_query)
    try:
        response = client.get("/api/v1/productions")
    finally:
        event.remove(connection, "before_cursor_execute", count_tombstone_query)

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert {item["id"] for item in response.json()["items"]} == {
        str(productions["public"].id),
        str(productions["about"].id),
    }
    assert tombstone_query_count == 1


def test_public_list_returns_only_current_metadata_public_records(
    client: TestClient, productions: dict[str, Production]
) -> None:
    response = client.get("/api/v1/productions?territory_relation=produced_in_pe")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    item = body["items"][0]
    assert item["id"] == str(productions["public"].id)
    assert item["title"] == "Tecnologia social para saneamento rural"
    assert item["publication_year"] == 2024
    assert item["territory_relations"] == ["produced_in_pe"]
    assert item["institutions"] == ["Universidade Federal de Pernambuco"]
    assert item["authors"] == ["Bruno Barros", "Carla Costa"]
    assert "Alice Andrade" not in str(body)
    assert "Título anterior" not in str(body)
    assert "Instituição histórica" not in str(body)
    assert "semantic_assertions" not in item


def test_public_list_supports_exact_filters_and_pagination(
    client: TestClient, productions: dict[str, Production]
) -> None:
    filters = {
        "institution": "Universidade Federal de Pernambuco",
        "type": "social_technology",
        "publication_year": "2024",
        "territory_relation": "produced_in_pe",
    }
    for field, value in filters.items():
        response = client.get("/api/v1/productions", params={field: value})
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["id"] == str(productions["public"].id)

    partial_institution = client.get(
        "/api/v1/productions", params={"institution": "Federal"}
    )
    assert partial_institution.status_code == 200
    assert partial_institution.json()["total"] == 0
    historical_institution = client.get(
        "/api/v1/productions",
        params={"institution": "Instituição histórica que não deve aparecer"},
    )
    assert historical_institution.status_code == 200
    assert historical_institution.json()["total"] == 0

    first_page = client.get("/api/v1/productions", params={"page": 1, "page_size": 1})
    second_page = client.get("/api/v1/productions", params={"page": 2, "page_size": 1})
    assert first_page.status_code == second_page.status_code == 200
    assert first_page.json()["total"] == second_page.json()["total"] == 2
    assert first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]


def test_public_detail_exposes_provenance_quality_and_no_internal_fields(
    client: TestClient, productions: dict[str, Production]
) -> None:
    response = client.get(f"/api/v1/productions/{productions['public'].id}")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == {
        "code": "fixture",
        "name": "Fixture Repository",
        "source_identifier": "oai:fixture:public-v2",
        "source_url": "https://repository.example/items/1",
        "access_status": "available",
    }
    assert body["quality"]["missing_fields"] == ["abstract"]
    assert body["abstract"] is None
    assert body["authors"] == ["Bruno Barros", "Carla Costa"]
    forbidden = {
        "raw_payload",
        "payload",
        "normalization_report",
        "audit_events",
        "duplicate_candidates",
        "semantic_assertions",
        "canonical_key",
        "current_version_number",
        "visibility",
    }
    assert forbidden.isdisjoint(body)


def test_missing_source_link_is_reported_as_unavailable(
    client: TestClient, productions: dict[str, Production]
) -> None:
    response = client.get(f"/api/v1/productions/{productions['about'].id}")

    assert response.status_code == 200
    assert response.json()["source"]["source_url"] is None
    assert response.json()["source"]["access_status"] == "unavailable"


def test_private_and_unknown_details_are_indistinguishable(
    client: TestClient, productions: dict[str, Production]
) -> None:
    private = client.get(f"/api/v1/productions/{productions['private'].id}")
    unknown = client.get(f"/api/v1/productions/{uuid.uuid4()}")

    assert private.status_code == unknown.status_code == 404
    assert private.json() == unknown.json() == {"detail": "Production not found"}


@pytest.mark.parametrize("page", [1, 1_000_000])
def test_public_list_accepts_supported_page_boundaries(
    client: TestClient, page: int
) -> None:
    response = client.get("/api/v1/productions", params={"page": page})

    assert response.status_code == 200
    assert response.json()["page"] == page


@pytest.mark.parametrize("page", [0, 1_000_001, 10**100])
def test_public_list_rejects_pages_outside_supported_bounds(
    client: TestClient, page: int
) -> None:
    response = client.get("/api/v1/productions", params={"page": page})

    assert response.status_code == 422


@pytest.mark.parametrize("publication_year", [1, 9999])
def test_public_list_accepts_supported_publication_year_boundaries(
    client: TestClient, publication_year: int
) -> None:
    response = client.get(
        "/api/v1/productions", params={"publication_year": publication_year}
    )

    assert response.status_code == 200


@pytest.mark.parametrize("publication_year", [0, 10_000, 10**100])
def test_public_list_rejects_publication_years_outside_supported_bounds(
    client: TestClient, publication_year: int
) -> None:
    response = client.get(
        "/api/v1/productions", params={"publication_year": publication_year}
    )

    assert response.status_code == 422
