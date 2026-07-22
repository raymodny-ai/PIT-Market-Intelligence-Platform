"""Panels API tests (TODO T-10 acceptance)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from pit_market.api.main import app
from pit_market.pit.builder import PitPanelBuilder

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def client_with_panel(tmp_path: Path):
    """Set up: build a real panel on disk, then spin TestClient."""
    silver = pl.DataFrame([
        {
            "observation_id": f"obs_{i}",
            "canonical_symbol": "QQQ",
            "field_name": "price__yf__close",
            "value": 100.0 + i,
            "price_type": "RAW_CLOSE",
            "observation_time": datetime(2024, 1, 1 + i, 16, 0, tzinfo=UTC),
            "available_at": datetime(2024, 1, 2 + i, 18, 0, tzinfo=UTC),
            "valid_from": datetime(2024, 1, 1 + i, 16, 0, tzinfo=UTC),
            "valid_to": None,
            "source_name": "yfinance",
            "dataset_name": "daily_ohlcv",
            "quality_status": "VALID",
            "quality_flags_json": "{}",
            "fill_type": "OBSERVED",
            "raw_record_hash": f"hash_{i}",
        }
        for i in range(3)
    ])
    panels_dir = tmp_path / "pit_panels"
    import os
    os.environ["GOLD_PANELS_DIR"] = str(panels_dir)

    builder = PitPanelBuilder(silver_df=silver)
    result = builder.build(
        decision_time=datetime(2024, 1, 15, 18, 0, tzinfo=UTC),
        universe=["QQQ"],
        output_dir=panels_dir,
    )
    with TestClient(app) as c:
        yield c, result.panel_id, panels_dir


class TestHealthEndpoint:
    def test_health(self):
        with TestClient(app) as c:
            r = c.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "registry_hash" in body


class TestPanels:
    def test_latest(self, client_with_panel):
        c, panel_id, _ = client_with_panel
        r = c.get("/v1/panels/latest")
        assert r.status_code == 200
        body = r.json()
        assert body["panel_id"] == panel_id

    def test_get_panel(self, client_with_panel):
        c, panel_id, _ = client_with_panel
        r = c.get(f"/v1/panels/{panel_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["panel_id"] == panel_id
        assert body["quality_status"] == "GOOD"

    def test_get_missing_panel(self, client_with_panel):
        c, _, _ = client_with_panel
        r = c.get("/v1/panels/nonexistent")
        assert r.status_code == 404


class TestSliceDiscipline:
    def test_unmapped_symbol_rejected(self, client_with_panel):
        c, panel_id, _ = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["FAKE_QQQ"]},
        )
        assert r.status_code == 400
        assert "UNMAPPED_SYMBOL" in r.json()["detail"]

    def test_unknown_field_rejected(self, client_with_panel):
        c, panel_id, _ = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ"], "fields": ["bogus__field"]},
        )
        assert r.status_code == 400
        assert "UNKNOWN_FIELD" in r.json()["detail"]

    def test_valid_slice(self, client_with_panel):
        c, panel_id, _ = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["panel_id"] == panel_id
        assert body["row_count"] >= 1


class TestRegistry:
    def test_metrics_registry(self, client_with_panel):
        c, _, _ = client_with_panel
        r = c.get("/v1/metrics/registry")
        assert r.status_code == 200
        body = r.json()
        assert "flow__finra__short_ratio" in body["fields"]
        assert "非全市场" in body["fields"]["flow__finra__short_ratio"]["semantic_warning"]

    def test_instruments_registry(self, client_with_panel):
        c, _, _ = client_with_panel
        r = c.get("/v1/instruments/registry")
        assert r.status_code == 200
        body = r.json()
        assert "QQQ" in body["instruments"]
        assert body["instruments"]["GLD"]["cot_report_type"] == "DISAGGREGATED"
