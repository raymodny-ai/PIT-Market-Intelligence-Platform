"""Tests for CLI-built (manifest-only) panels.

When a panel only has a `_manifest.json` (CLI layout) and no
`value_panel.parquet`, the API should still resolve it via
`_resolve_panel()` and return an empty catalog rather than 404.

This unblocks /v1/analyses for panels built by `pit-market pit build`,
which only writes the manifest.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Import app AFTER env var is set (main.py reads GOLD_PANELS_DIR at lifespan)


@pytest.fixture
def manifest_only_client(tmp_path: Path, monkeypatch):
    """Client whose panels_dir has only flat `{id}_manifest.json` files.

    Mirrors what `pit-market pit build` produces (no parquet, no nested dir).
    """
    panels_dir = tmp_path / "pit_panels"
    panels_dir.mkdir()
    monkeypatch.setenv("GOLD_PANELS_DIR", str(panels_dir))
    monkeypatch.setenv("PIT_CONFIG_DIR", str(Path("config").resolve()))
    monkeypatch.setenv("PIT_MARKET_DATA", str(tmp_path))

    # Lazy import so the env var is read at lifespan startup
    from pit_market.api.main import app  # noqa: PLC0415

    # Write a CLI-style manifest (no parquet, flat layout)
    panel_id = "cli-20260115T180500Z-SPY-QQQ-GLD-SLV"
    manifest = {
        "panel_id": panel_id,
        "decision_time_utc": "2026-01-15T18:05:00+00:00",
        "decision_clock": "1805_ET",
        "universe": ["SPY", "QQQ", "GLD", "SLV"],
        "registry_hash": "0" * 64,
        "feature_version": "features.v1.0",
        "metric_registry_version": "metrics.v1.0",
        "instrument_registry_version": "registry.v1.0",
    }
    (panels_dir / f"{panel_id}_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    with TestClient(app) as c:
        yield c, panel_id


class TestManifestOnlyPanel:
    def test_evidence_endpoint_returns_empty_catalog(
        self, manifest_only_client
    ) -> None:
        c, panel_id = manifest_only_client
        r = c.post(f"/v1/analyses/evidence/{panel_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["catalog_id"] == "catalog_empty"
        assert body["evidence_count"] == 0
        assert body["sample"] == []
        assert "2026-01-15" in body["decision_time"]

    def test_analysis_endpoint_publishes_no_evidence_finding(
        self, manifest_only_client
    ) -> None:
        c, panel_id = manifest_only_client
        r = c.post(
            "/v1/analyses",
            json={"panel_id": panel_id, "provider": "mock"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # With mock provider + empty catalog, finding is None and status REJECTED.
        # The escape hatch in validator.py allows DATA_QUALITY_ISSUE+NO_EVIDENCE
        # but the mock analyzer doesn't produce that classification — it emits
        # a finding with empty evidence_ids, which rule 1 still rejects.
        assert body["status"] == "REJECTED"
        assert body["catalog_id"] == "catalog_empty"
        assert body["finding"] is None
        # Errors must mention rule 1 (the original guard)
        assert any("rule 1" in e for e in body["errors"])

    def test_unknown_panel_still_returns_404(self, manifest_only_client) -> None:
        c, _ = manifest_only_client
        r = c.post("/v1/analyses/evidence/cli-does-not-exist")
        assert r.status_code == 404
        assert "Panel not found" in r.json()["detail"]

    def test_panel_listing_includes_manifest_only_panels(
        self, manifest_only_client
    ) -> None:
        c, panel_id = manifest_only_client
        r = c.get("/v1/panels")
        assert r.status_code == 200
        ids = [p["panel_id"] for p in r.json()["panels"]]
        assert panel_id in ids