import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pci.models.enums import RecordVisibility
from pci.models.production import Production
from pci.models.provenance import Source
from pci.models.publication import PublishedContribution
from pci.problems.models import PublicProblem
from tests.api.conftest import RecordFactory


@pytest.fixture
def search_records(record_factory: RecordFactory, fixture_source: Source, session: Session):
    fixture_source.schedule = {"institution_sector": "public", "institution_state": "PE"}
    records = {}
    for key, title, year, kind, visibility, abstract in [
        (
            "title",
            "Segurança do paciente na atenção básica",
            2023,
            "dissertation",
            RecordVisibility.METADATA_PUBLIC,
            "Estudo sobre organização do cuidado.",
        ),
        (
            "abstract",
            "Gestão de serviços",
            2024,
            "thesis",
            RecordVisibility.METADATA_PUBLIC,
            "A pesquisa analisa segurança do paciente na rede de saúde.",
        ),
        (
            "other",
            "Saneamento rural",
            2022,
            "dissertation",
            RecordVisibility.METADATA_PUBLIC,
            "Tratamento de água.",
        ),
        (
            "private",
            "Segurança do paciente reservada",
            2024,
            "thesis",
            RecordVisibility.PRIVATE,
            "CONTEUDO_INTERNO_NAO_PUBLICAR",
        ),
        (
            "old",
            "Segurança do paciente em 2015",
            2015,
            "thesis",
            RecordVisibility.METADATA_PUBLIC,
            None,
        ),
        (
            "current",
            "Segurança do paciente em 2026",
            2026,
            "thesis",
            RecordVisibility.METADATA_PUBLIC,
            None,
        ),
        (
            "article",
            "Segurança do paciente em artigo",
            2024,
            "article",
            RecordVisibility.METADATA_PUBLIC,
            None,
        ),
    ]:
        records[key] = record_factory(
            source_identifier=f"oai:search:{key}",
            title=title,
            doi=f"10.8000/{key}",
            institution="Universidade Federal de Pernambuco",
            publication_year=year,
            production_type=kind,
            visibility=visibility,
            abstract=abstract,
        )
    session.flush()
    return records


def test_one_expression_returns_ranked_public_corpus_without_creating_a_problem(
    client: TestClient,
    session: Session,
    search_records: dict[str, Production],
) -> None:
    response = client.get("/api/v1/productions/search", params={"q": "seguranca do paciente"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [
        str(search_records[k].id) for k in ("title", "abstract")
    ]
    assert body["items"][0]["matched_terms"] == ["seguranca", "paciente"]
    assert body["items"][0]["abstract"] == "Estudo sobre organização do cuidado."
    assert body["items"][0]["validated_contributions"] == []
    assert session.scalar(select(func.count()).select_from(PublicProblem)) == 0
    assert "CONTEUDO_INTERNO_NAO_PUBLICAR" not in response.text


def test_search_filters_sort_and_pagination_preserve_the_query(
    client: TestClient,
    search_records: dict[str, Production],
) -> None:
    params = {"q": "segurança paciente", "page_size": 1}
    first = client.get("/api/v1/productions/search", params=params).json()
    second = client.get("/api/v1/productions/search", params={**params, "page": 2}).json()
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    recent = client.get("/api/v1/productions/search", params={**params, "sort": "recent"}).json()
    assert recent["items"][0]["id"] == str(search_records["abstract"].id)
    filtered = client.get(
        "/api/v1/productions/search", params={**params, "type": "thesis", "publication_year": 2024}
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["id"] == str(search_records["abstract"].id)
    assert filtered["facets"]["years"] == [2024, 2023]


def test_search_only_uses_active_published_scientific_contributions(
    client: TestClient,
    session: Session,
    search_records: dict[str, Production],
) -> None:
    for active, description in [(True, "Biofiltro comunitário"), (False, "MARCADOR_REVOGADO")]:
        session.add(
            PublishedContribution(
                scientific_contribution_id=uuid.uuid4(),
                contribution_version_id=uuid.uuid4(),
                production_id=search_records["other"].id,
                version=1,
                scientific_values={"description": description},
                approved_groundings=[],
                active=active,
            )
        )
    session.flush()
    body = client.get("/api/v1/productions/search", params={"q": "biofiltro"}).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == str(search_records["other"].id)
    assert len(item["validated_contributions"]) == 1
    assert (
        item["validated_contributions"][0]["scientific_values"]["description"]
        == "Biofiltro comunitário"
    )
    assert "MARCADOR_REVOGADO" not in str(body)
    revoked = client.get("/api/v1/productions/search", params={"q": "MARCADOR_REVOGADO"}).json()
    assert revoked["total"] == 0
    field_name = client.get("/api/v1/productions/search", params={"q": "description"}).json()
    assert field_name["total"] == 0


def test_search_respects_the_institutional_corpus(
    client: TestClient,
    fixture_source: Source,
    session: Session,
    search_records: dict[str, Production],
) -> None:
    fixture_source.schedule = {"institution_sector": "private", "institution_state": "PE"}
    session.flush()
    response = client.get("/api/v1/productions/search", params={"q": "segurança"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.parametrize("query", ["", "  ", "a", "de para como", "x" * 301])
def test_empty_or_uninformative_search_is_rejected(client: TestClient, query: str) -> None:
    assert client.get("/api/v1/productions/search", params={"q": query}).status_code == 422


def test_unmatched_expression_has_an_explicit_empty_result(
    client: TestClient,
    search_records: dict[str, Production],
) -> None:
    response = client.get("/api/v1/productions/search", params={"q": "astrobiologia"})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
