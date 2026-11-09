"""Synthetic evidence fixtures; no invented records enter the production corpus."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

from pci.answers.provider import HttpAnswerProvider
from pci.answers.schemas import Analysis, EvidenceSource
from pci.models.documents import (
    DocumentPage,
    DocumentTextScope,
    DocumentTextVersion,
    SourceDocument,
    SourceDocumentStatus,
    TextExtractionMethod,
)
from pci.models.enums import RecordVisibility, RightsPolicy
from pci.models.production import ProductionVersion
from pci.models.provenance import RawRecord
from pci.models.publication import PublishedContribution

ABSTRACT = "O estudo de saneamento rural avaliou filtros comunitários e identificou a necessidade de manutenção periódica."


@pytest.fixture
def answer_records(record_factory, fixture_source):
    fixture_source.schedule = {"institution_sector": "public", "institution_state": "PE"}
    records = {}
    for key, visibility, year, abstract in [
        ("public", RecordVisibility.METADATA_PUBLIC, 2023, ABSTRACT),
        ("private", RecordVisibility.PRIVATE, 2023, "SEGREDO_INTERNO saneamento rural"),
        ("old", RecordVisibility.METADATA_PUBLIC, 2015, "FORA_DO_RECORTE saneamento rural"),
    ]:
        records[key] = record_factory(
            source_identifier=f"oai:answer:{key}",
            title=f"Saneamento rural {key}",
            doi=f"10.9999/{key}",
            institution="Universidade Federal de Pernambuco",
            publication_year=year,
            production_type="dissertation",
            visibility=visibility,
            abstract=abstract,
        )
    return records


class RecordingProvider:
    def __init__(self, *, invalid=None):
        self.sources, self.calls, self.invalid = [], 0, invalid

    def synthesize(self, query, sources):
        self.sources, self.calls = sources, self.calls + 1
        excerpt = sources[0].excerpts[0]
        citation = {"excerpt_id": excerpt.id, "quote": excerpt.text[:100]}
        if self.invalid == "quote":
            citation["quote"] = "TRECHO QUE NAO EXISTE NO TEXTO"
        if self.invalid == "id":
            citation["excerpt_id"] = "S999-E1"
        statement = {
            "text": "O estudo sugere um caminho condicionado à manutenção e à avaliação local.",
            "basis": "inference",
            "citations": [citation],
        }
        return Analysis.model_validate(
            {
                "outcome": "conditional",
                "context": [statement],
                "feasibility": [statement],
                "pathways": [statement],
                "potentials": [],
                "limitations": [statement],
            }
        )


def test_public_cited_answer_does_not_publish(client, session, answer_records):
    provider = RecordingProvider()
    client.app.state.answer_provider = provider
    before = session.scalar(select(func.count()).select_from(PublishedContribution))
    response = client.post(
        "/api/v1/answers", json={"q": "Quero resolver o problema de saneamento rural"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["message"].endswith("a aplicação exige avaliação local.")
    assert body["total_matches"] == 1
    assert len(body["sources"]) == 1
    assert body["sources"][0]["production_id"] == str(answer_records["public"].id)
    assert body["sources"][0]["reading_scope"] == "abstract_only"
    assert "SEGREDO_INTERNO" not in str(provider.sources)
    assert "FORA_DO_RECORTE" not in response.text
    assert body["analysis"]["feasibility"][0]["citations"][0]["excerpt_id"] == "S1-E1"
    assert body["validation_status"] == "automated_unreviewed"
    assert response.headers["cache-control"] == "no-store"
    assert session.scalar(select(func.count()).select_from(PublishedContribution)) == before


def test_disabled_provider_never_fabricates_answer(client, answer_records, monkeypatch):
    monkeypatch.setenv("ANSWER_ENABLED", "false")
    body = client.post("/api/v1/answers", json={"q": "saneamento"}).json()
    assert body["status"] == "unavailable" and body["analysis"] is None
    assert body["message"].endswith("trabalhos encontrados abaixo.")


@pytest.mark.parametrize(
    "query",
    [
        {"q": "inexistente"},
        {"q": "saneamento", "type": "thesis"},
        {"q": "saneamento", "publication_year": 2024},
    ],
)
def test_empty_or_filtered_search_does_not_call_model(client, answer_records, query):
    provider = RecordingProvider()
    client.app.state.answer_provider = provider
    body = client.post("/api/v1/answers", json=query).json()
    assert body["status"] == "insufficient_evidence" and body["analysis"] is None
    assert provider.calls == 0


def test_no_text_cannot_generate_from_title(client, record_factory, fixture_source):
    fixture_source.schedule = {"institution_sector": "public", "institution_state": "PE"}
    record_factory(
        source_identifier="oai:no-text",
        title="Resíduos sólidos",
        doi="10.0000/no-text",
        institution="UFPE",
        publication_year=2023,
        production_type="thesis",
    )
    provider = RecordingProvider()
    client.app.state.answer_provider = provider
    body = client.post("/api/v1/answers", json={"q": "resíduos"}).json()
    assert body["status"] == "insufficient_evidence" and body["total_matches"] == 1
    assert provider.calls == 0


@pytest.mark.parametrize("invalid", ["quote", "id"])
def test_invalid_citations_are_rejected(client, answer_records, invalid):
    client.app.state.answer_provider = RecordingProvider(invalid=invalid)
    body = client.post("/api/v1/answers", json={"q": "saneamento"}).json()
    assert body["status"] == "unavailable" and body["analysis"] is None
    assert body["message"].endswith("disponíveis abaixo.")
    assert "TRECHO QUE NAO EXISTE" not in str(body)


@pytest.mark.parametrize("q", ["a", "de para com", "x" * 301])
def test_invalid_expression(client, q):
    assert client.post("/api/v1/answers", json={"q": q}).status_code == 422


def add_full_text(session, production, text):
    current = session.scalar(
        select(ProductionVersion).where(
            ProductionVersion.production_id == production.id,
            ProductionVersion.version == production.current_version_number,
        )
    )
    # Fixture-only setup of immutable raw metadata, never performed by answers.
    session.execute(
        RawRecord.__table__.update()
        .where(RawRecord.id == current.raw_record_id)
        .values(rights_snapshot="open_copy")
    )
    doc = SourceDocument(
        production_version_id=current.id,
        status=SourceDocumentStatus.TEXT_EXTRACTED,
        rights_snapshot="open_copy",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.add(doc)
    session.flush()
    session.add(
        DocumentTextVersion(
            source_document_id=doc.id,
            production_version_id=current.id,
            version=1,
            normalized_text=text,
            scope=DocumentTextScope.FULL_TEXT,
            extraction_method=TextExtractionMethod.PYPDF,
            checksum="a" * 64,
            pages=[
                DocumentPage(
                    page_number=12, start_offset=0, end_offset=len(text), checksum="b" * 64
                )
            ],
        )
    )
    session.flush()
    return current


def test_full_text_pages_and_rights_fallback(client, session, fixture_source, answer_records):
    fixture_source.rights_policy = RightsPolicy.OPEN_COPY
    text = "Saneamento rural: o ensaio de filtros apresentou resultados limitados ao laboratório."
    add_full_text(session, answer_records["public"], text)
    provider = RecordingProvider()
    client.app.state.answer_provider = provider
    body = client.post("/api/v1/answers", json={"q": "saneamento"}).json()
    assert body["sources"][0]["reading_scope"] == "full_text_excerpts"
    assert body["sources"][0]["excerpts"][0]["page"] == 12
    assert provider.sources[0].excerpts[0].text == text
    fixture_source.rights_policy = RightsPolicy.METADATA_ONLY
    session.flush()
    body = client.post("/api/v1/answers", json={"q": "saneamento"}).json()
    assert body["sources"][0]["reading_scope"] == "abstract_only"
    assert "limitados ao laboratório" not in str(provider.sources)


def test_new_restriction_without_text_blocks_previous_full_text(
    client, session, record_factory, fixture_source
):
    fixture_source.schedule = {"institution_sector": "public", "institution_state": "PE"}
    fixture_source.rights_policy = RightsPolicy.OPEN_COPY
    production = record_factory(
        source_identifier="oai:revoked",
        title="Transporte público",
        doi="10.9999/revoked",
        institution="UFPE",
        publication_year=2023,
        production_type="thesis",
        abstract=None,
    )
    version = add_full_text(
        session, production, "Transporte público: TEXTO_AGORA_RESTRITO não pode sair do sistema."
    )
    session.add(
        SourceDocument(
            production_version_id=version.id,
            status=SourceDocumentStatus.RESTRICTED,
            rights_snapshot="restricted",
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
    )
    session.flush()
    provider = RecordingProvider()
    client.app.state.answer_provider = provider
    body = client.post("/api/v1/answers", json={"q": "transporte"}).json()
    assert provider.calls == 0
    assert body["status"] == "insufficient_evidence"
    assert "TEXTO_AGORA_RESTRITO" not in str(body)


def test_previous_production_version_is_not_used(client, record_factory, answer_records):
    record_factory(
        source_identifier="oai:answer:public-new",
        title="Saneamento rural atualizado",
        doi="10.9999/public",
        institution="Universidade Federal de Pernambuco",
        publication_year=2024,
        production_type="dissertation",
        abstract=None,
    )
    provider = RecordingProvider()
    client.app.state.answer_provider = provider
    body = client.post("/api/v1/answers", json={"q": "saneamento"}).json()
    assert body["status"] == "insufficient_evidence" and provider.calls == 0


def test_insufficient_is_not_impossible(client, answer_records):
    class InsufficientProvider:
        def synthesize(self, query, sources):
            return Analysis(
                outcome="insufficient",
                context=[],
                feasibility=[],
                pathways=[],
                potentials=[],
                limitations=[],
            )

    client.app.state.answer_provider = InsufficientProvider()
    body = client.post("/api/v1/answers", json={"q": "saneamento"}).json()
    assert body["status"] == "insufficient_evidence"
    assert body["message"].endswith("Isso não significa impossibilidade.")


def test_http_provider_sends_schema_and_public_evidence(client, answer_records):
    def handler(request):
        data = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer fixture-key"
        assert data["store"] is False
        assert data["response_format"]["json_schema"]["strict"] is True
        material = json.loads(data["messages"][1]["content"])
        sources = [EvidenceSource.model_validate(s) for s in material["sources"]]
        assert len(sources) == 1 and sources[0].excerpts[0].text == ABSTRACT
        analysis = RecordingProvider().synthesize(material["problem"], sources)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": analysis.model_dump_json()}}
                ]
            },
        )

    client.app.state.answer_provider = HttpAnswerProvider(
        "https://provider.example/chat/completions",
        "fixture-key",
        "test-model",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.post("/api/v1/answers", json={"q": "saneamento"}).json()["status"] == "ready"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"finish_reason": "stop", "message": None}]},
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {
            "choices": [
                {"finish_reason": "stop", "message": {"refusal": "refused", "content": None}}
            ]
        },
        {"choices": [{"finish_reason": "stop", "message": {"content": "{not-json"}}]},
    ],
)
def test_bad_provider_responses_fail_closed(client, answer_records, payload):
    client.app.state.answer_provider = HttpAnswerProvider(
        "https://provider.example/chat/completions",
        "test-key",
        "test-model",
        http=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ),
    )
    body = client.post("/api/v1/answers", json={"q": "saneamento"}).json()
    assert body["status"] == "unavailable" and body["analysis"] is None


def test_timeout_does_not_expose_provider_details(client, answer_records):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("confidential provider detail")

    client.app.state.answer_provider = HttpAnswerProvider(
        "https://provider.example/chat/completions",
        "test-key",
        "test-model",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    body = client.post("/api/v1/answers", json={"q": "saneamento"}).json()
    assert body["status"] == "unavailable" and body["analysis"] is None
    assert "confidential" not in str(body) and len(calls) == 1


def test_material_is_bounded(client, record_factory, answer_records):
    for i in range(8):
        record_factory(
            source_identifier=f"oai:extra-{i}",
            title=f"Saneamento rural {i}",
            doi=f"10.9999/extra-{i}",
            institution="UFPE",
            publication_year=2024,
            production_type="dissertation",
            abstract=ABSTRACT * 100,
        )
    provider = RecordingProvider()
    client.app.state.answer_provider = provider
    body = client.post("/api/v1/answers", json={"q": "saneamento"}).json()
    assert body["total_matches"] == 9 and len(provider.sources) == 5
    assert sum(len(e.text) for s in provider.sources for e in s.excerpts) <= 27000
