from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pci.auth.dependencies import CuratorDependency
from pci.auth.oidc import LocalTokenVerifier
from pci.main import create_app


@pytest.fixture
def local_verifier() -> LocalTokenVerifier:
    return LocalTokenVerifier(
        secret="local-secret-long-enough-for-tests",
        issuer="observainova-local",
        audience="observainova-api",
    )


def make_token(*roles: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "observainova-local",
            "sub": "person-123",
            "aud": "observainova-api",
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "name": "Pessoa da Equipe Central",
            "roles": list(roles),
        },
        "local-secret-long-enough-for-tests",
        algorithm="HS256",
    )


@pytest.fixture
def internal_client(local_verifier: LocalTokenVerifier) -> TestClient:
    app: FastAPI = create_app()
    app.state.token_verifier = local_verifier

    @app.get("/api/v1/internal/auth-check/curator")
    def curator_check(principal: CuratorDependency) -> dict[str, str]:
        return {"actor": principal.actor_key}

    return TestClient(app)


def test_internal_route_requires_a_bearer_token(internal_client: TestClient) -> None:
    response = internal_client.get("/api/v1/internal/auth-check/curator")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_curator_route_rejects_supervisor_only_token(internal_client: TestClient) -> None:
    response = internal_client.get(
        "/api/v1/internal/auth-check/curator",
        headers={"Authorization": f"Bearer {make_token('supervisor')}"},
    )

    assert response.status_code == 403


def test_curator_route_accepts_curator_token(internal_client: TestClient) -> None:
    response = internal_client.get(
        "/api/v1/internal/auth-check/curator",
        headers={"Authorization": f"Bearer {make_token('curator')}"},
    )

    assert response.status_code == 200
    assert response.json() == {"actor": "observainova-local|person-123"}
