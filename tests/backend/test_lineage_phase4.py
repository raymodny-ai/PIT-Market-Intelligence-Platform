"""Phase 4 lineage + source health tests (T-27 / T-28)."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pit_market.api.main import app


@pytest.fixture
def client_with_manifests(tmp_path: Path):
    """Seed raw/ and analyses/ with sample manifests."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    panels_dir = tmp_path / "pit_panels"
    panels_dir.mkdir(parents=True, exist_ok=True)

    # Three sources, varying quality
    for src, ds, q, n in [
        ("yfinance", "daily_ohlcv", "VALID", 100),
        ("cftc", "disagg_cot", "VALID", 50),
        ("finra", "regsho_daily", "SOURCE_FAILED", 0),
    ]:
        run_id = f"run_{src}_001"
        run_dir = raw_dir / f"source={src}" / f"dataset={ds}" / "ingest_date=2024-07-20" / f"run_id={run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "request.json").write_text("{}", encoding="utf-8")
        (run_dir / "response_headers.json").write_text("{}", encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps({
            "source_name": src,
            "dataset_name": ds,
            "ingest_date": "2024-07-20",
            "run_id": run_id,
            "record_count": n,
            "quality_status": q,
        }), encoding="utf-8")

    os.environ["GOLD_PANELS_DIR"] = str(panels_dir)
    with TestClient(app) as c:
        yield c, panels_dir


# =============================================================================
# T-27: Source Health
# =============================================================================


class TestSourceHealth:
    def test_status_endpoint(self, client_with_manifests):
        c, _ = client_with_manifests
        r = c.get("/v1/sources/status")
        assert r.status_code == 200
        body = r.json()
        assert "yfinance" in body["sources"]
        assert "cftc" in body["sources"]
        assert "finra" in body["sources"]
        yf = body["sources"]["yfinance"]
        assert yf["run_count"] >= 1
        assert yf["total_records"] >= 100

    def test_failure_counted(self, client_with_manifests):
        c, _ = client_with_manifests
        r = c.get("/v1/sources/status")
        body = r.json()
        finra = body["sources"]["finra"]
        assert finra["error_count"] >= 1
        assert finra["last_quality_status"] == "SOURCE_FAILED"

    def test_source_events(self, client_with_manifests):
        c, _ = client_with_manifests
        r = c.get("/v1/sources/yfinance/events")
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == "yfinance"
        assert len(body["events"]) >= 1
        assert all(e["quality_status"] == "VALID" for e in body["events"])

    def test_source_events_unknown_source(self, client_with_manifests):
        c, _ = client_with_manifests
        r = c.get("/v1/sources/nonexistent/events")
        body = r.json()
        assert body["events"] == []


# =============================================================================
# T-28: Lineage
# =============================================================================


class TestLineage:
    def test_evidence_lineage(self, client_with_manifests):
        c, _ = client_with_manifests
        r = c.get("/v1/lineage/ev_test_evidence_001")
        assert r.status_code == 200
        body = r.json()
        assert "graph" in body
        assert "lineage" in body
        # Graph has 5 nodes (5-level chain)
        assert len(body["graph"]["nodes"]) == 5
        assert len(body["graph"]["edges"]) == 4

    def test_finding_lineage(self, client_with_manifests):
        c, _ = client_with_manifests
        r = c.get("/v1/lineage/finding_test_001")
        assert r.status_code == 200
        body = r.json()
        assert body["entity_id"] == "finding_test_001"

    def test_analysis_facet(self, client_with_manifests):
        c, panels_dir = client_with_manifests
        # Run an analysis first
        import polars as pl

        from pit_market.pit.builder import PitPanelBuilder
        silver = pl.DataFrame([{
            "observation_id": "o1", "canonical_symbol": "QQQ",
            "field_name": "price__yf__close", "value": 100.0,
            "price_type": "RAW_CLOSE",
            "observation_time": datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
            "available_at": datetime(2024, 1, 9, 18, 0, tzinfo=UTC),
            "valid_from": datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
            "valid_to": None, "source_name": "yfinance",
            "dataset_name": "daily_ohlcv", "frequency": "daily",
            "quality_status": "VALID", "quality_flags_json": "{}",
            "fill_type": "OBSERVED", "raw_record_hash": "x" * 64,
        }])
        result = PitPanelBuilder(silver_df=silver).build(
            datetime(2024, 1, 10, 12, 0, tzinfo=UTC), ["QQQ"],
            output_dir=panels_dir,
        )
        a = c.post(
            "/v1/analyses",
            json={"panel_id": result.panel_id, "provider": "mock"},
        )
        run_id = a.json()["analysis_run_id"]
        r = c.get(f"/v1/lineage/analysis/{run_id}/facet")
        assert r.status_code == 200
        facet = r.json()
        assert facet["_producer"] == "pit-market"
        assert facet["_schemaURL"].endswith("LLMProvenanceRunFacet.json")
        assert facet["model"] == "mock"
        assert facet["validation_status"] in ("VALIDATED", "REJECTED")

    def test_analysis_facet_404(self, client_with_manifests):
        c, _ = client_with_manifests
        r = c.get("/v1/lineage/analysis/nonexistent_run/facet")
        assert r.status_code == 404
