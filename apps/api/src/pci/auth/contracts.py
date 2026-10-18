from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Role(str, Enum):
    CURATOR = "curator"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    issuer: str
    subject: str
    display_name: str | None
    roles: frozenset[Role]

    @property
    def actor_key(self) -> str:
        return f"{self.issuer}|{self.subject}"


class AuthenticationError(Exception):
    """A bearer token could not be authenticated."""


class TokenVerifier(Protocol):
    def verify(self, token: str) -> AuthPrincipal: ...
