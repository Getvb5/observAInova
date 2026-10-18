from collections.abc import Callable
from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request, status

from pci.auth.contracts import AuthenticationError, AuthPrincipal, Role, TokenVerifier
from pci.auth.oidc import LocalTokenVerifier, OidcTokenVerifier
from pci.settings import Settings


def _configured_verifier() -> TokenVerifier:
    settings = Settings()  # type: ignore[call-arg]
    if settings.auth_mode == "oidc":
        return OidcTokenVerifier.from_settings(settings)
    return LocalTokenVerifier(
        secret=settings.local_auth_secret,
        issuer=settings.local_auth_issuer,
        audience=settings.oidc_audience,
    )


def _unauthorized(detail: str = "Invalid bearer token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthPrincipal:
    if authorization is None:
        raise _unauthorized("Bearer token required")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        raise _unauthorized("Bearer token required")
    verifier = cast(TokenVerifier | None, getattr(request.app.state, "token_verifier", None))
    if verifier is None:
        verifier = _configured_verifier()
        request.app.state.token_verifier = verifier
    try:
        return verifier.verify(token)
    except AuthenticationError as exc:
        raise _unauthorized() from exc


PrincipalDependency = Annotated[AuthPrincipal, Depends(get_principal)]


def require_roles(*roles: Role) -> Callable[[AuthPrincipal], AuthPrincipal]:
    required_roles = frozenset(roles)

    def check_roles(principal: PrincipalDependency) -> AuthPrincipal:
        if principal.roles.isdisjoint(required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return principal

    return check_roles


CuratorDependency = Annotated[AuthPrincipal, Depends(require_roles(Role.CURATOR))]
SupervisorDependency = Annotated[AuthPrincipal, Depends(require_roles(Role.SUPERVISOR))]
AdminDependency = Annotated[AuthPrincipal, Depends(require_roles(Role.ADMIN))]
