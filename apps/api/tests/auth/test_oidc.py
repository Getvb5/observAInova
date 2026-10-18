from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from pci.auth.contracts import AuthenticationError, Role
from pci.auth.oidc import OidcTokenVerifier
from pci.settings import Settings


class StaticSigningKey:
    def __init__(self, key: object) -> None:
        self.key = key


class StaticJwksClient:
    def __init__(self, key: object) -> None:
        self.key = key
        self.calls = 0

    def get_signing_key_from_jwt(self, _: str) -> StaticSigningKey:
        self.calls += 1
        return StaticSigningKey(self.key)


@pytest.fixture
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def verifier(private_key: rsa.RSAPrivateKey) -> OidcTokenVerifier:
    return OidcTokenVerifier(
        issuer="https://identity.example",
        audience="observainova-api",
        algorithms=("RS256",),
        roles_claim="roles",
        role_map={"reviewer": Role.CURATOR, "publisher": Role.SUPERVISOR},
        jwks_client=StaticJwksClient(private_key.public_key()),
    )


@pytest.fixture
def token_factory(
    private_key: rsa.RSAPrivateKey,
) -> Callable[..., str]:
    def create_token(
        *,
        issuer: str = "https://identity.example",
        audience: str = "observainova-api",
        expires_in: int = 300,
        roles: list[str] | None = None,
        algorithm: str = "RS256",
    ) -> str:
        now = datetime.now(UTC)
        claims: dict[str, Any] = {
            "iss": issuer,
            "sub": "person-123",
            "aud": audience,
            "exp": now + timedelta(seconds=expires_in),
            "iat": now,
            "name": "Pessoa Curadora",
            "roles": roles if roles is not None else ["reviewer", "ignored-role"],
        }
        return jwt.encode(claims, private_key, algorithm=algorithm)

    return create_token


def test_oidc_maps_only_configured_roles_and_builds_stable_actor_key(
    verifier: OidcTokenVerifier,
    token_factory: Callable[..., str],
) -> None:
    principal = verifier.verify(token_factory())

    assert principal.actor_key == "https://identity.example|person-123"
    assert principal.display_name == "Pessoa Curadora"
    assert principal.roles == frozenset({Role.CURATOR})


def test_oidc_rejects_wrong_issuer_audience_and_expired_tokens(
    verifier: OidcTokenVerifier,
    token_factory: Callable[..., str],
) -> None:
    for token in (
        token_factory(issuer="https://wrong.example"),
        token_factory(audience="wrong-api"),
        token_factory(expires_in=-1),
    ):
        with pytest.raises(AuthenticationError):
            verifier.verify(token)


def test_oidc_rejects_an_algorithm_outside_the_allow_list(
    verifier: OidcTokenVerifier,
) -> None:
    token = jwt.encode(
        {
            "iss": "https://identity.example",
            "sub": "person-123",
            "aud": "observainova-api",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "local-secret-long-enough-for-tests",
        algorithm="HS256",
    )

    with pytest.raises(AuthenticationError):
        verifier.verify(token)


def test_local_auth_cannot_start_in_production() -> None:
    with pytest.raises(ValueError, match="local authentication"):
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            object_storage_endpoint="http://localhost:9000",
            object_storage_bucket="test",
            app_env="production",
            auth_mode="local",
            local_auth_secret="secret",
        )
