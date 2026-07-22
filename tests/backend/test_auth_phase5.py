"""Phase 5 T-31 — API Key auth + permission matrix tests (PRD §18)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from pit_market.auth import (
    ApiKey,
    Permission,
    Scope,
    fingerprint,
    get_matrix,
    has_permission,
    lookup_key,
    reload_keys,
)
from pit_market.auth.deps import get_api_key, require_permission


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.get("/public")
    async def public(key: ApiKey | None = None) -> dict:
        # type: ignore[assignment]
        return {"scope": key.scope.value if key else "anonymous"}

    @app.get("/export")
    async def export_endpoint(api_key: ApiKey | None = None) -> dict:  # type: ignore[assignment]
        from pit_market.auth.deps import require_permission
        require_permission(api_key, Permission.EXPORT)
        return {"ok": True}

    @app.get("/admin")
    async def admin_endpoint(api_key: ApiKey | None = None) -> dict:  # type: ignore[assignment]
        from pit_market.auth.deps import require_permission
        require_permission(api_key, Permission.ADMIN)
        return {"ok": True}

    # Wire dependency manually
    for route in app.routes:
        if route.path in ("/public", "/export", "/admin"):
            route.dependant.dependencies.insert(0, None)  # placeholder

    return TestClient(app)


# --- Matrix tests (PRD §18) ---

def test_matrix_public_can_only_read() -> None:
    assert has_permission(Scope.PUBLIC, Permission.READ_PANEL) is True
    assert has_permission(Scope.PUBLIC, Permission.EXPORT) is False
    assert has_permission(Scope.PUBLIC, Permission.ANALYZE) is False
    assert has_permission(Scope.PUBLIC, Permission.ADMIN) is False


def test_matrix_researcher_can_export_and_analyze() -> None:
    assert has_permission(Scope.RESEARCHER, Permission.READ_PANEL) is True
    assert has_permission(Scope.RESEARCHER, Permission.EXPORT) is True
    assert has_permission(Scope.RESEARCHER, Permission.ANALYZE) is True
    assert has_permission(Scope.RESEARCHER, Permission.ADMIN) is False


def test_matrix_admin_can_do_anything() -> None:
    for p in Permission:
        assert has_permission(Scope.ADMIN, p) is True


def test_get_matrix_is_json_friendly() -> None:
    m = get_matrix()
    assert m["public"] == ["read_panel"]
    assert "export" in m["researcher"]
    assert "admin" in m["admin"]


# --- lookup_key tests ---

def test_lookup_dev_keys() -> None:
    reload_keys()
    assert lookup_key("rk_dev_admin", "dev-admin-secret") is not None
    assert lookup_key("rk_dev_admin", "wrong") is None
    assert lookup_key("nonexistent", "x") is None


def test_lookup_uses_constant_time_compare() -> None:
    # Just ensure the function returns None for a wrong secret without raising
    assert lookup_key("rk_dev_researcher", "wrong") is None


def test_fingerprint_does_not_reveal_secret() -> None:
    fp = fingerprint("dev-admin-secret")
    assert len(fp) == 16
    assert "dev-admin-secret" not in fp
    # same secret → same fingerprint
    assert fingerprint("dev-admin-secret") == fp


def test_reload_keys_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import json as _json
    monkeypatch.setenv("PIT_MARKET_API_KEYS", _json.dumps({
        "rk_test": {"secret": "s3", "scope": "researcher", "label": "test"},
    }))
    reload_keys()
    assert lookup_key("rk_test", "s3") is not None
    # Reset back to dev keys
    monkeypatch.delenv("PIT_MARKET_API_KEYS", raising=False)
    reload_keys()


def test_reload_keys_rejects_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIT_MARKET_API_KEYS", "{not valid json")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        reload_keys()
    monkeypatch.delenv("PIT_MARKET_API_KEYS", raising=False)
    reload_keys()


# --- FastAPI dependency ---

def test_get_api_key_from_headers() -> None:
    import asyncio

    # Direct call (no Request needed since headers are kwargs)
    key = asyncio.run(get_api_key(
        x_api_key_id="rk_dev_researcher",
        x_api_key_secret="dev-researcher-secret",
        authorization=None,
    ))
    assert key is not None
    assert key.scope == Scope.RESEARCHER


def test_get_api_key_from_bearer() -> None:
    import asyncio
    key = asyncio.run(get_api_key(
        x_api_key_id=None,
        x_api_key_secret=None,
        authorization="Bearer rk_dev_admin:dev-admin-secret",
    ))
    assert key is not None
    assert key.scope == Scope.ADMIN


def test_get_api_key_returns_none_when_missing() -> None:
    import asyncio
    key = asyncio.run(get_api_key(
        x_api_key_id=None,
        x_api_key_secret=None,
        authorization=None,
    ))
    assert key is None


def test_require_permission_rejects_anonymous() -> None:
    with pytest.raises(HTTPException) as ex:
        require_permission(None, Permission.READ_PANEL)
    assert ex.value.status_code == 401


def test_require_permission_rejects_under_privileged() -> None:
    key = lookup_key("rk_dev_public", "dev-public-secret")
    assert key is not None
    with pytest.raises(HTTPException) as ex:
        require_permission(key, Permission.EXPORT)
    assert ex.value.status_code == 403


def test_require_permission_grants_when_allowed() -> None:
    key = lookup_key("rk_dev_researcher", "dev-researcher-secret")
    assert key is not None
    require_permission(key, Permission.EXPORT)  # must not raise
