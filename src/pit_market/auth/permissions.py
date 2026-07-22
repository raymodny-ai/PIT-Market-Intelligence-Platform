"""API Key authentication + permission matrix (PRD §18, T-31).

The platform exposes a small permission matrix:

    scope         | read panel | export | analyze | admin
    --------------|------------|--------|---------|------
    public        |     ✓      |   ✗    |    ✗    |  ✗
    researcher    |     ✓      |   ✓    |    ✓    |  ✗
    admin         |     ✓      |   ✓    |    ✓    |  ✓

Keys are loaded from ``PIT_MARKET_API_KEYS`` env var (JSON dict) or a
default dev key when unset. In production the env var MUST be set.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from enum import StrEnum


class Scope(StrEnum):
    PUBLIC = "public"
    RESEARCHER = "researcher"
    ADMIN = "admin"


class Permission(StrEnum):
    READ_PANEL = "read_panel"
    EXPORT = "export"
    ANALYZE = "analyze"
    ADMIN = "admin"


# Permission matrix: scope → set of granted permissions
_MATRIX: dict[Scope, frozenset[Permission]] = {
    Scope.PUBLIC: frozenset({Permission.READ_PANEL}),
    Scope.RESEARCHER: frozenset({
        Permission.READ_PANEL, Permission.EXPORT, Permission.ANALYZE,
    }),
    Scope.ADMIN: frozenset({
        Permission.READ_PANEL, Permission.EXPORT, Permission.ANALYZE, Permission.ADMIN,
    }),
}


@dataclass(frozen=True)
class ApiKey:
    """A single API key with its scope. The key bytes are never logged."""

    key_id: str        # public identifier (e.g. "rk_dev_001")
    key_secret: str    # secret (hashed before storage in real deployments)
    scope: Scope
    label: str = ""


def _default_keys() -> dict[str, ApiKey]:
    """Built-in dev keys — only used when PIT_MARKET_API_KEYS is unset."""
    return {
        "rk_dev_public": ApiKey(
            key_id="rk_dev_public",
            key_secret="dev-public-secret",
            scope=Scope.PUBLIC,
            label="dev public",
        ),
        "rk_dev_researcher": ApiKey(
            key_id="rk_dev_researcher",
            key_secret="dev-researcher-secret",
            scope=Scope.RESEARCHER,
            label="dev researcher",
        ),
        "rk_dev_admin": ApiKey(
            key_id="rk_dev_admin",
            key_secret="dev-admin-secret",
            scope=Scope.ADMIN,
            label="dev admin",
        ),
    }


def _load_keys_from_env() -> dict[str, ApiKey]:
    raw = os.environ.get("PIT_MARKET_API_KEYS", "").strip()
    if not raw:
        return _default_keys()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"PIT_MARKET_API_KEYS is not valid JSON: {e}") from e
    out: dict[str, ApiKey] = {}
    for key_id, body in data.items():
        scope = Scope(body["scope"])
        out[key_id] = ApiKey(
            key_id=key_id,
            key_secret=body["secret"],
            scope=scope,
            label=body.get("label", ""),
        )
    return out


_KEYS: dict[str, ApiKey] = _load_keys_from_env()


def reload_keys() -> None:
    """Re-read ``PIT_MARKET_API_KEYS`` — used by tests and admin endpoints."""
    global _KEYS
    _KEYS = _load_keys_from_env()


def list_keys() -> list[ApiKey]:
    """List registered keys (secrets NOT included in the response)."""
    return list(_KEYS.values())


def lookup_key(key_id: str, key_secret: str) -> ApiKey | None:
    """Constant-time lookup. Returns the ApiKey or None."""
    candidate = _KEYS.get(key_id)
    if candidate is None:
        return None
    if not hmac.compare_digest(candidate.key_secret.encode("utf-8"),
                                key_secret.encode("utf-8")):
        return None
    return candidate


def permissions_for(scope: Scope) -> frozenset[Permission]:
    return _MATRIX.get(scope, frozenset())


def has_permission(scope: Scope, perm: Permission) -> bool:
    return perm in permissions_for(scope)


def fingerprint(key_secret: str) -> str:
    """SHA-256 fingerprint for audit logs (does not reveal the secret)."""
    return hashlib.sha256(key_secret.encode("utf-8")).hexdigest()[:16]


def get_matrix() -> dict[str, list[str]]:
    """Render the matrix as a JSON-friendly dict (for /healthcheck)."""
    return {
        s.value: sorted(p.value for p in perms)
        for s, perms in _MATRIX.items()
    }
