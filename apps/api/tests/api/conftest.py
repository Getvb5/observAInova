import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pci.main import create_app
from pci.models.enums import RecordVisibility, RightsPolicy, TerritoryRelation
from pci.models.production import Production
from pci.models.provenance import RawRecord, Source
from pci.models.territory import ProductionTerritory, Territory
from pci.normalization.service import persist_normalized_record

RecordFactory = Callable[..., Production]


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.state.session_factory = lambda: session
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fixture_source(session: Session) -> Source:
    source = Source(
        code="fixture",
        name="Fixture Repository",
        connector_type="fixture",
        base_url="https://repository.example/oai",
        rights_policy=RightsPolicy.METADATA_ONLY,
    )
    session.add(source)
    session.flush()
    return source


@pytest.fixture
def record_factory(session: Session, fixture_source: Source) -> RecordFactory:
    def create_record(
        *,
        source_identifier: str,
        title: str,
        doi: str,
        institution: str,
        publication_year: int,
        production_type: str,
        visibility: RecordVisibility = RecordVisibility.METADATA_PUBLIC,
        source_url: str | None = "https://repository.example/items/1",
        abstract: str | None = None,
        author_organization: str | None = None,
        authors: list[dict[str, str] | str] | None = None,
        territory_relation: TerritoryRelation | None = None,
    ) -> Production:
        author: dict[str, str] = {"name": "Ana Silva"}
        if author_organization is not None:
            author["organization"] = author_organization
        payload: dict[str, Any] = {
            "title": title,
            "authors": authors if authors is not None else [author],
            "institution": institution,
            "publication_date": str(publication_year),
            "type": production_type,
            "language": "pt-BR",
            "keywords": ["inovação"],
            "doi": doi,
        }
        if abstract is not None:
            payload["abstract"] = abstract
        raw = RawRecord(
            source_id=fixture_source.id,
            source_identifier=source_identifier,
            payload=payload,
            source_url=source_url,
            checksum=uuid.uuid4().hex,
            rights_snapshot="metadata-only",
        )
        session.add(raw)
        session.flush()
        production_id = persist_normalized_record(session, raw.id)
        production = session.get(Production, production_id)
        assert production is not None
        production.visibility = visibility
        if territory_relation is not None:
            territory = session.query(Territory).filter_by(code="pe").one_or_none()
            if territory is None:
                territory = Territory(code="pe", name="Pernambuco")
                session.add(territory)
                session.flush()
            session.add(
                ProductionTerritory(
                    production_id=production.id,
                    territory_id=territory.id,
                    relation=territory_relation,
                )
            )
        session.flush()
        return production

    return create_record


@pytest.fixture
def productions(record_factory: RecordFactory) -> dict[str, Production]:
    old = record_factory(
        source_identifier="oai:fixture:public-v1",
        title="Título anterior que não deve aparecer",
        doi="10.1000/public",
        institution="Instituição histórica que não deve aparecer",
        publication_year=2023,
        production_type="article",
        authors=[
            {"name": "Alice Andrade", "organization": "Instituto Alice"},
            {"name": "Bruno Barros", "organization": "Instituto Antigo"},
        ],
    )
    current = record_factory(
        source_identifier="oai:fixture:public-v2",
        title="Tecnologia social para saneamento rural",
        doi="10.1000/public",
        institution="Universidade Federal de Pernambuco",
        publication_year=2024,
        production_type="social_technology",
        authors=[
            {"name": "Bruno Barros", "organization": "Instituto Atual"},
            "Carla Costa",
        ],
        territory_relation=TerritoryRelation.PRODUCED_IN_PE,
    )
    assert old.id == current.id
    about = record_factory(
        source_identifier="oai:fixture:about",
        title="Mudanças climáticas no litoral pernambucano",
        doi="10.1000/about",
        institution="Instituto Federal de Pernambuco",
        publication_year=2022,
        production_type="article",
        source_url=None,
        abstract="Estudo costeiro.",
        territory_relation=TerritoryRelation.ABOUT_PE,
    )
    private = record_factory(
        source_identifier="oai:fixture:private",
        title="Registro reservado",
        doi="10.1000/private",
        institution="Universidade de Pernambuco",
        publication_year=2024,
        production_type="article",
        visibility=RecordVisibility.PRIVATE,
        abstract="Não publicar.",
    )
    return {"public": current, "about": about, "private": private}
