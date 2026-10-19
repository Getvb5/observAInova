import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pci.models.publication import PublishedContribution
from pci.problems.models import (
    ProblemAnswerEvent,
    ProblemContextVersion,
    PublicProblem,
)


def complete_api_answers() -> list[tuple[str, str, str]]:
    return [
        ("territory", "Caruaru", "reported_fact"),
        (
            "affected_population_or_service",
            "adultos aguardando cardiologia",
            "reported_fact",
        ),
        ("observed_consequences", "espera superior a 90 dias", "reported_fact"),
        ("perceived_causes", "oferta insuficiente, segundo a equipe", "perception"),
        ("attempted_actions", "remanejamento manual de vagas", "reported_fact"),
        (
            "available_resources",
            "equipe de regulação e dados de agenda",
            "reported_fact",
        ),
        ("constraints", "sem aumento de equipe", "reported_fact"),
        ("desired_outcome", "reduzir a espera preservando equidade", "reported_fact"),
    ]


def create_problem(client: TestClient) -> tuple[str, str]:
    created = client.post(
        "/api/v1/problems",
        json={"description": "As pessoas aguardam muito por consultas especializadas"},
    )
    assert created.status_code == 201
    return created.json()["problem_id"], created.json()["edit_token"]


def answer_complete_problem(client: TestClient, problem_id: str, token: str) -> None:
    headers = {"X-Problem-Token": token}
    for field, value, knowledge_status in complete_api_answers():
        response = client.post(
            f"/api/v1/problems/{problem_id}/answers",
            headers=headers,
            json={
                "field": field,
                "value": value,
                "knowledge_status": knowledge_status,
            },
        )
        assert response.status_code == 200


def test_problem_flow_from_description_to_confirmation(client: TestClient) -> None:
    created = client.post(
        "/api/v1/problems",
        json={"description": "As pessoas aguardam muito por consultas especializadas"},
    )

    assert created.status_code == 201
    problem_id = created.json()["problem_id"]
    token = created.json()["edit_token"]
    state = created.json()["state"]
    assert state["next_question"]["field"] == "territory"
    assert state["status"] == "draft"
    assert state["map_status"] == "not_ready"

    answer_complete_problem(client, problem_id, token)
    headers = {"X-Problem-Token": token}
    review = client.get(f"/api/v1/problems/{problem_id}", headers=headers)
    assert review.status_code == 200
    assert review.json()["ready_to_confirm"] is True
    assert review.json()["structured_summary"] is not None
    assert review.json()["fields"]["constraints"]["value"] == "sem aumento de equipe"

    confirmed = client.post(f"/api/v1/problems/{problem_id}/confirm", headers=headers)
    assert confirmed.status_code == 201
    assert confirmed.json()["current_version"] == 1
    assert confirmed.json()["map_status"] == "awaiting_validated_contributions"
    assert "edit_token" not in confirmed.json()


@pytest.mark.parametrize("description", ["", "   ", "x" * 5001])
def test_invalid_description_never_creates_problem(
    client: TestClient, session: Session, description: str
) -> None:
    response = client.post("/api/v1/problems", json={"description": description})

    assert response.status_code == 422
    assert session.query(PublicProblem).count() == 0


@pytest.mark.parametrize("value", ["", "   ", "x" * 5001])
def test_invalid_answer_never_creates_event(
    client: TestClient, session: Session, value: str
) -> None:
    problem_id, token = create_problem(client)

    response = client.post(
        f"/api/v1/problems/{problem_id}/answers",
        headers={"X-Problem-Token": token},
        json={
            "field": "territory",
            "value": value,
            "knowledge_status": "reported_fact",
        },
    )

    assert response.status_code == 422
    assert session.scalar(select(func.count()).select_from(ProblemAnswerEvent)) == 0


def test_unknown_answer_remains_null_and_advances_dialogue(client: TestClient) -> None:
    problem_id, token = create_problem(client)

    response = client.post(
        f"/api/v1/problems/{problem_id}/answers",
        headers={"X-Problem-Token": token},
        json={
            "field": "territory",
            "value": None,
            "knowledge_status": "unknown",
        },
    )

    assert response.status_code == 200
    assert response.json()["fields"]["territory"] == {
        "value": None,
        "knowledge_status": "unknown",
    }
    assert response.json()["next_question"]["field"] == "affected_population_or_service"
    assert "território provável" not in str(response.json()).lower()


def test_early_confirmation_returns_ordered_missing_fields(client: TestClient) -> None:
    problem_id, token = create_problem(client)

    response = client.post(
        f"/api/v1/problems/{problem_id}/confirm",
        headers={"X-Problem-Token": token},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "problem_incomplete",
        "missing_fields": [
            "territory",
            "affected_population_or_service",
            "observed_consequences",
            "perceived_causes",
            "attempted_actions",
            "available_resources",
            "constraints",
            "desired_outcome",
        ],
    }


def test_confirmed_problem_requires_reopen_and_creates_version_two(
    client: TestClient, session: Session
) -> None:
    problem_id, token = create_problem(client)
    headers = {"X-Problem-Token": token}
    answer_complete_problem(client, problem_id, token)
    first_confirmation = client.post(
        f"/api/v1/problems/{problem_id}/confirm", headers=headers
    )
    assert first_confirmation.status_code == 201
    first_version = session.scalar(
        select(ProblemContextVersion).where(ProblemContextVersion.version == 1)
    )
    assert first_version is not None
    first_constraints = first_version.context["constraints"]["value"]

    blocked = client.post(
        f"/api/v1/problems/{problem_id}/answers",
        headers=headers,
        json={
            "field": "constraints",
            "value": "Sem aumento de equipe e orçamento",
            "knowledge_status": "reported_fact",
        },
    )
    assert blocked.status_code == 409

    reopened = client.post(f"/api/v1/problems/{problem_id}/revisions", headers=headers)
    assert reopened.status_code == 200
    corrected = client.post(
        f"/api/v1/problems/{problem_id}/answers",
        headers=headers,
        json={
            "field": "constraints",
            "value": "Sem aumento de equipe e orçamento",
            "knowledge_status": "reported_fact",
        },
    )
    assert corrected.status_code == 200
    second_confirmation = client.post(
        f"/api/v1/problems/{problem_id}/confirm", headers=headers
    )

    assert second_confirmation.status_code == 201
    assert second_confirmation.json()["current_version"] == 2
    assert first_version.context["constraints"]["value"] == first_constraints
    second_version = session.scalar(
        select(ProblemContextVersion).where(ProblemContextVersion.version == 2)
    )
    assert second_version is not None
    assert second_version.context["constraints"]["value"] == (
        "Sem aumento de equipe e orçamento"
    )


def test_wrong_missing_and_unknown_problem_are_indistinguishable(
    client: TestClient,
) -> None:
    problem_id, token = create_problem(client)

    wrong = client.get(
        f"/api/v1/problems/{problem_id}", headers={"X-Problem-Token": "wrong"}
    )
    missing = client.get(f"/api/v1/problems/{problem_id}")
    unknown = client.get(
        f"/api/v1/problems/{uuid.uuid4()}",
        headers={"X-Problem-Token": token},
    )

    assert wrong.status_code == missing.status_code == unknown.status_code == 404
    assert wrong.json() == missing.json() == unknown.json() == {
        "detail": "Problem not found"
    }


def test_extra_request_keys_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/problems",
        json={"description": "Problema válido", "publish": True},
    )

    assert response.status_code == 422


def test_confirmed_problem_map_returns_only_matching_published_contributions(
    client: TestClient, session: Session
) -> None:
    problem_id, token = create_problem(client)
    answer_complete_problem(client, problem_id, token)
    headers = {"X-Problem-Token": token}
    confirmed = client.post(f"/api/v1/problems/{problem_id}/confirm", headers=headers)
    assert confirmed.status_code == 201

    matching = PublishedContribution(
        scientific_contribution_id=uuid.uuid4(),
        contribution_version_id=uuid.uuid4(),
        production_id=uuid.uuid4(),
        version=1,
        contribution_type="method",
        scientific_values={
            "problem_or_phenomenon": "Espera por consultas de cardiologia",
            "description": "Método de regulação da fila de cardiologia",
            "evidence_results": "Redução do tempo de espera para consultas",
            "barriers_limitations": "Depende da qualidade dos dados da agenda",
            "applicability": "Serviços públicos de regulação ambulatorial",
        },
        approved_groundings=[],
        institution="UFPE",
        publication_year=2024,
        source_scope="full_text",
        production_type="dissertation",
        active=True,
    )
    unpublished = PublishedContribution(
        scientific_contribution_id=uuid.uuid4(),
        contribution_version_id=uuid.uuid4(),
        production_id=uuid.uuid4(),
        version=1,
        contribution_type="method",
        scientific_values={
            "description": "Outra proposta para reduzir a espera em cardiologia",
        },
        approved_groundings=[],
        institution="UFPE",
        publication_year=2023,
        source_scope="abstract_only",
        production_type="thesis",
        active=False,
    )
    unrelated = PublishedContribution(
        scientific_contribution_id=uuid.uuid4(),
        contribution_version_id=uuid.uuid4(),
        production_id=uuid.uuid4(),
        version=1,
        contribution_type="diagnosis",
        scientific_values={
            "description": "Diagnóstico de fungos em plantações de melão",
        },
        approved_groundings=[],
        institution="UFPE",
        publication_year=2022,
        source_scope="full_text",
        production_type="thesis",
        active=True,
    )
    session.add_all([matching, unpublished, unrelated])
    session.flush()

    response = client.get(
        f"/api/v1/problems/{problem_id}/evidence-map",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["problem_version"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["scientific_contribution_id"] == str(
        matching.scientific_contribution_id
    )
    assert "cardiologia" in body["items"][0]["matched_terms"]
    assert "candidate" not in response.text.lower()


def test_confirmed_problem_map_reports_an_explicit_evidence_gap(
    client: TestClient,
) -> None:
    problem_id, token = create_problem(client)
    answer_complete_problem(client, problem_id, token)
    headers = {"X-Problem-Token": token}
    client.post(f"/api/v1/problems/{problem_id}/confirm", headers=headers)

    response = client.get(
        f"/api/v1/problems/{problem_id}/evidence-map",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "no_validated_evidence"
    assert response.json()["items"] == []
