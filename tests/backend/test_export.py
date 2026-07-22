"""Phase 2 export + 4-mode reports (T-17, T-18 acceptance)."""
from __future__ import annotations

import json
import os
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
    rows = [
        {
            "observation_id": f"o{i}",
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
            "frequency": "daily",
            "quality_status": "VALID",
            "quality_flags_json": "{}",
            "fill_type": "OBSERVED",
            "raw_record_hash": f"hash_{i}",
        }
        for i in range(3)
    ]
    silver = pl.DataFrame(rows)
    panels_dir = tmp_path / "pit_panels"
    os.environ["GOLD_PANELS_DIR"] = str(panels_dir)
    r = PitPanelBuilder(silver_df=silver).build(
        datetime(2024, 2, 1, 12, 0, tzinfo=UTC), ["QQQ"], output_dir=panels_dir
    )
    with TestClient(app) as c:
        yield c, r.panel_id


# =============================================================================
# T-18: Export
# =============================================================================


class TestExport:
    def test_csv_export(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/export/panels/{panel_id}?format=csv",
            json={"universe": ["QQQ"]},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        body = r.text
        assert "QQQ" in body
        # Manifest in header
        manifest = json.loads(r.headers["x-export-manifest"])
        assert manifest["panel_id"] == panel_id
        assert len(manifest["slice_request_sha256"]) == 64
        assert len(manifest["data_response_sha256"]) == 64

    def test_parquet_export(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/export/panels/{panel_id}?format=parquet",
            json={"universe": ["QQQ"]},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/octet-stream")
        manifest = json.loads(r.headers["x-export-manifest"])
        assert "export_id" in manifest
        assert "report_version" in manifest

    def test_json_export(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/export/panels/{panel_id}?format=json",
            json={"universe": ["QQQ"]},
        )
        assert r.status_code == 200
        body = json.loads(r.text)
        assert isinstance(body, list)

    def test_unsupported_format(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/export/panels/{panel_id}?format=docx",
            json={"universe": ["QQQ"]},
        )
        assert r.status_code == 400

    def test_empty_slice(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/export/panels/{panel_id}?format=csv",
            json={"universe": ["FAKE"]},
        )
        assert r.status_code == 400 or r.status_code == 404

    def test_manifest_hashes_stable(self, client_with_panel):
        c, panel_id = client_with_panel
        r1 = c.post(
            f"/v1/export/panels/{panel_id}?format=json",
            json={"universe": ["QQQ"]},
        )
        r2 = c.post(
            f"/v1/export/panels/{panel_id}?format=json",
            json={"universe": ["QQQ"]},
        )
        m1 = json.loads(r1.headers["x-export-manifest"])
        m2 = json.loads(r2.headers["x-export-manifest"])
        # Same request → same slice_request_sha256
        assert m1["slice_request_sha256"] == m2["slice_request_sha256"]
        # Same data → same data_response_sha256
        assert m1["data_response_sha256"] == m2["data_response_sha256"]
