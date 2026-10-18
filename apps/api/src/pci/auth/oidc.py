from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

import jwt

from pci.auth.contracts import AuthenticationError, AuthPrincipal, Role
from pci.settings import Settings


class SigningKey(Protocol):
    key: Any


class JwksClient(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> SigningKey: ...


def _read_claim(claims: Mapping[str, Any], path: str) -> object:
    value: object = claims
    for segment in path.split("."):
        if not isinstance(value, Mapping) or segment not in value:
            return ()
        value = value[segment]
    return value


def _claim_values(value: object) -> Sequence[str]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _principal_from_claims(
    claims: Mapping[str, Any],
    *,
    roles_claim: str,
    role_map: Mapping[str, Role],
) -> AuthPrincipal:
    issuer = claims.get("iss")
    subject = claims.get("sub")
    if not isinstance(issuer, str) or not isinstance(subject, str):
        raise AuthenticationError("token identity claims are invalid")
    name = claims.get("name")
    if not isinstance(name, str):
        preferred_username = claims.get("preferred_username")
        name = preferred_username if isinstance(preferred_username, str) else None
    mapped_roles = frozenset(
        role_map[value]
        for value in _claim_values(_read_claim(claims, roles_claim))
        if value in role_map
    )
    return AuthPrincipal(
        issuer=issuer,
        subject=subject,
        display_name=name,
        roles=mapped_roles,
    )


class OidcTokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        algorithms: tuple[str, ...],
        roles_claim: str,
        role_map: Mapping[str, Role],
        jwks_client: JwksClient,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._algorithms = algorithms
        self._roles_claim = roles_claim
        self._role_map = dict(role_map)
        self._jwks_client = jwks_client

    @classmethod
    def from_settings(cls, settings: Settings) -> "OidcTokenVerifier":
        role_map: dict[str, Role] = {}
        for claim_value, role_value in settings.oidc_role_map.items():
            try:
                role_map[claim_value] = Role(role_value)
            except ValueError as exc:
                raise ValueError(f"unknown configured role: {role_value}") from exc
        return cls(
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            algorithms=settings.oidc_algorithms,
            roles_claim=settings.oidc_roles_claim,
            role_map=role_map,
            jwks_client=cast(JwksClient, jwt.PyJWKClient(settings.oidc_jwks_url)),
        )

    def verify(self, token: str) -> AuthPrincipal:
        try:
            algorithm = jwt.get_unverified_header(token).get("alg")
            if algorithm not in self._algorithms:
                raise AuthenticationError("token algorithm is not allowed")
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self._algorithms),
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "sub", "aud"]},
            )
            return _principal_from_claims(
                claims,
                roles_claim=self._roles_claim,
                role_map=self._role_map,
            )
        except AuthenticationError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise AuthenticationError("bearer token is invalid") from exc


class LocalTokenVerifier:
    def __init__(self, *, secret: str, issuer: str, audience: str) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience

    def verify(self, token: str) -> AuthPrincipal:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "sub", "aud"]},
            )
            return _principal_from_claims(
                claims,
                roles_claim="roles",
                role_map={role.value: role for role in Role},
            )
        except AuthenticationError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise AuthenticationError("bearer token is invalid") from exc
