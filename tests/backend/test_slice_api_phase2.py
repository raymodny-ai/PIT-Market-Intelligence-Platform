"""Phase 2 Slice API + Cache + SSE tests (T-14 acceptance)."""
from __future__ import annotations

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
    """Build a multi-symbol, multi-field panel."""
    rows = []
    base = datetime(2024, 1, 1, 16, 0, tzinfo=UTC)
    for sym_i, sym in enumerate(["QQQ", "SPY", "GLD"]):
        for i in range(5):
            obs_time = base.replace(day=1 + i * 7)
            avail = obs_time.replace(hour=18)
            rows.append({
                "observation_id": f"obs_{sym_i}_{i}",
                "canonical_symbol": sym,
                "field_name": "price__yf__close" if i % 2 == 0 else "flow__finra__short_volume",
                "value": 100.0 + sym_i * 10 + i,
                "price_type": "RAW_CLOSE" if i % 2 == 0 else None,
                "observation_time": obs_time,
                "available_at": avail,
                "valid_from": obs_time,
                "valid_to": None,
                "source_name": "yfinance" if i % 2 == 0 else "finra",
                "dataset_name": "daily_ohlcv" if i % 2 == 0 else "regsho_daily",
                "frequency": "daily",
                "quality_status": "VALID",
                "quality_flags_json": "{}",
                "fill_type": "OBSERVED",
                "raw_record_hash": f"hash_{sym_i}_{i}",
            })
    silver = pl.DataFrame(rows)
    panels_dir = tmp_path / "pit_panels"
    os.environ["GOLD_PANELS_DIR"] = str(panels_dir)

    builder = PitPanelBuilder(silver_df=silver)
    result = builder.build(
        decision_time=datetime(2024, 2, 15, 18, 0, tzinfo=UTC),
        universe=["QQQ", "SPY", "GLD"],
        output_dir=panels_dir,
    )
    with TestClient(app) as c:
        yield c, result.panel_id


# =============================================================================
# T-14: Slice API enhancements
# =============================================================================


class TestSliceFilters:
    def test_universe_filter(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(f"/v1/panels/{panel_id}/slice", json={"universe": ["QQQ"]})
        assert r.status_code == 200
        body = r.json()
        assert all(row["canonical_symbol"] == "QQQ" for row in body["rows"])

    def test_field_filter(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ", "SPY"], "fields": ["price__yf__close"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert all(row["field_name"] == "price__yf__close" for row in body["rows"])

    def test_source_filter(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ", "SPY", "GLD"], "sources": ["finra"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert all(row["source_name"] == "finra" for row in body["rows"])

    def test_sort_asc(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={
                "universe": ["QQQ", "SPY", "GLD"],
                "sort": {"field": "value", "direction": "asc"},
            },
        )
        body = r.json()
        values = [row["value"] for row in body["rows"]]
        assert values == sorted(values)

    def test_sort_desc(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={
                "universe": ["QQQ", "SPY", "GLD"],
                "sort": {"field": "value", "direction": "desc"},
            },
        )
        body = r.json()
        values = [row["value"] for row in body["rows"]]
        assert values == sorted(values, reverse=True)

    def test_pagination(self, client_with_panel):
        c, panel_id = client_with_panel
        r1 = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ", "SPY", "GLD"], "page": {"offset": 0, "limit": 5}},
        )
        r2 = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ", "SPY", "GLD"], "page": {"offset": 5, "limit": 5}},
        )
        body1 = r1.json()
        body2 = r2.json()
        assert len(body1["rows"]) <= 5
        assert len(body2["rows"]) <= 5
        # No overlap
        ids1 = {row["observation_id"] for row in body1["rows"]}
        ids2 = {row["observation_id"] for row in body2["rows"]}
        assert ids1.isdisjoint(ids2)


class TestValidation:
    def test_invalid_domain_rejected(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ"], "domains": ["bogus"]},
        )
        assert r.status_code == 422

    def test_invalid_page_limit(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ"], "page": {"offset": 0, "limit": 10000}},
        )
        assert r.status_code == 422

    def test_invalid_clock(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ"], "decision_clock": "1300_ET"},
        )
        assert r.status_code == 422

    def test_universe_max_50(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": [f"SYM{i}" for i in range(60)]},
        )
        assert r.status_code == 422


# =============================================================================
# T-14: Cache + SSE
# =============================================================================


class TestCache:
    def test_cache_key_in_response(self, client_with_panel):
        c, panel_id = client_with_panel
        r = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ"]},
        )
        body = r.json()
        assert "cache_key" in body
        assert len(body["cache_key"]) == 32  # SHA256[:32]

    def test_same_request_same_key(self, client_with_panel):
        c, panel_id = client_with_panel
        r1 = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ"]},
        )
        r2 = c.post(
            f"/v1/panels/{panel_id}/slice",
            json={"universe": ["QQQ"]},
        )
        assert r1.json()["cache_key"] == r2.json()["cache_key"]


class TestSSE:
    def test_start_and_push(self, client_with_panel):
        c, _ = client_with_panel
        r = c.post("/v1/runs/run-001/start")
        assert r.status_code == 200
        r = c.post(
            "/v1/runs/run-001/progress",
            params={"status": "RUNNING", "progress_pct": 50, "message_zh": "处理中"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["event_count"] == 2  # QUEUED + RUNNING

    def test_sse_stream(self, client_with_panel):
        c, _ = client_with_panel
        c.post("/v1/runs/run-002/start")
        c.post(
            "/v1/runs/run-002/progress",
            params={"status": "RUNNING", "progress_pct": 50, "message_zh": "中"},
        )
        c.post(
            "/v1/runs/run-002/progress",
            params={"status": "COMPLETED", "progress_pct": 100, "message_zh": "完"},
        )
        with c.stream("GET", "/v1/runs/run-002/stream") as r:
            events = []
            for line in r.iter_lines():
                if line and not line.startswith(":"):
                    events.append(line)
        # We expect 3 events * 3 lines each (id, event, data) ≈ 9 lines
        assert any("run_status" in e for e in events)

    def test_sse_last_event_id_resume(self, client_with_panel):
        c, _ = client_with_panel
        c.post("/v1/runs/run-003/start")
        c.post(
            "/v1/runs/run-003/progress",
            params={"status": "RUNNING", "progress_pct": 50, "message_zh": "中"},
        )
        # Resume from event 1 (last received)
        with c.stream("GET", "/v1/runs/run-003/stream", headers={"Last-Event-ID": "run-003:0"}) as r:
            events = []
            for line in r.iter_lines():
                if line and not line.startswith(":"):
                    events.append(line)
        # Should include event 1 (RUNNING) but skip event 0
        assert any('"status": "RUNNING"' in e for e in events)
        assert not any('"status": "QUEUED"' in e for e in events)
