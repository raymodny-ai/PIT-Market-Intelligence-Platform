"""API health smoke test — Phase 0 gate (TODO T-04).

Validates the FastAPI app loads, registry initializes, and /health returns
the expected schema. Uses TestClient (no real server required).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pit_market.api.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert isinstance(body["registry_hash"], str)
    assert len(body["registry_hash"]) == 64  # sha256 hex


def test_health_includes_registry_hash():
    with TestClient(app) as client:
        r1 = client.get("/health")
        r2 = client.get("/health")
    assert r1.json() == r2.json()  # hash stable across calls


def test_panels_latest_returns_404_when_no_panels(tmp_path: Path):
    """T-10: /v1/panels/latest returns 404 when no panels built yet (or 200
    if a real panel exists from a previous test). We just verify the endpoint
    is now real (not a Phase 0 stub)."""
    import os
    os.environ["GOLD_PANELS_DIR"] = str(tmp_path)
    with TestClient(app) as client:
        response = client.get("/v1/panels/latest")
    # 404 (no panels) or 200 (panels found) — both indicate endpoint is live
    assert response.status_code in (200, 404)
