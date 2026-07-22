"""FastAPI dependency: extract an authenticated ApiKey from the request.

Headers:
    X-API-Key-Id: <key_id>
    X-API-Key-Secret: <secret>

OR a single header:
    Authorization: Bearer <key_id>:<secret>
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from pit_market.auth.permissions import ApiKey, Permission, has_permission


async def get_api_key(
    x_api_key_id: str | None = Header(default=None, alias="X-API-Key-Id"),
    x_api_key_secret: str | None = Header(default=None, alias="X-API-Key-Secret"),
    authorization: str | None = Header(default=None),
) -> ApiKey | None:
    """Return the matched ApiKey, or None if the request is unauthenticated.

    Endpoints decide whether auth is required. Public endpoints (e.g. /health)
    accept None; protected endpoints call :func:`require_permission`.
    """
    from pit_market.auth.permissions import lookup_key

    if x_api_key_id and x_api_key_secret:
        return lookup_key(x_api_key_id, x_api_key_secret)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
        if ":" in token:
            kid, secret = token.split(":", 1)
            return lookup_key(kid, secret)
    return None


def require_permission(api_key: ApiKey | None, perm: Permission) -> None:
    """Raise 401/403 if the key cannot perform ``perm``."""
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not has_permission(api_key.scope, perm):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Scope '{api_key.scope.value}' cannot perform '{perm.value}'",
        )
