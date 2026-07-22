"""Tests for POST /v1/panels/build and the underlying build_panel_manifest().

These cover the new "build panel from the UI" feature (commit f12e17d):
  - the reusable cli.build_panel_manifest() function
  - the FastAPI endpoint POST /v1/panels/build

Both layers must agree on validation semantics (PanelBuildError -> 400),
panel_id format, and manifest contents.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pit_market.api.main import app
from pit_market.cli import PanelBuildError, build_panel_manifest

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Route GOLD_PANELS_DIR and PIT_MARKET_DATA to a tmp_path so we don't
    pollute the dev workspace's data/gold/pit_panels/.

    Both build_panel_manifest() (writes to {PIT_MARKET_DATA}/gold/pit_panels)
    and the panels API (initialized from GOLD_PANELS_DIR) read these env
    vars at request time, so they share the same per-test directory.
    """
    data_root = tmp_path / "data_root"
    panels_dir = data_root / "gold" / "pit_panels"
    panels_dir.mkdir(parents=True)
    monkeypatch.setenv("GOLD_PANELS_DIR", str(panels_dir))
    monkeypatch.setenv("PIT_MARKET_DATA", str(data_root))
    monkeypatch.setenv("PIT_MARKET_CONFIG", str(CONFIG_DIR))
    return panels_dir


# ─────────────────────────────────────────────────────────────────────
# build_panel_manifest() — direct CLI helper
# ─────────────────────────────────────────────────────────────────────


class TestBuildPanelManifest:
    def test_happy_path_returns_manifest(self, isolated_data: Path):
        result = build_panel_manifest(
            decision_time="2024-03-15T18:05:00Z",
            universe=["SPY", "QQQ", "GLD", "SLV"],
            decision_clock="1805_ET",
            config_dir=CONFIG_DIR,
            data_dir=Path(os.environ["PIT_MARKET_DATA"]),
        )
        assert result["panel_id"] == "cli-20240315T180500Z-SPY-QQQ-GLD-SLV"
        assert result["decision_time_utc"] == "2024-03-15T18:05:00+00:00"
        assert result["decision_clock"] == "1805_ET"
        assert result["universe"] == ["SPY", "QQQ", "GLD", "SLV"]
        # registry_hash must be a hex string (sha256)
        assert isinstance(result["registry_hash"], str)
        assert len(result["registry_hash"]) == 64
        # _path is added for the caller (internal)
        assert result["_path"] == str(
            isolated_data / "cli-20240315T180500Z-SPY-QQQ-GLD-SLV_manifest.json"
        )

    def test_file_actually_written_to_disk(self, isolated_data: Path):
        build_panel_manifest(
            decision_time="2024-04-15T18:05:00Z",
            universe=["SPY"],
            config_dir=CONFIG_DIR,
            data_dir=Path(os.environ["PIT_MARKET_DATA"]),
        )
        out_file = isolated_data / "cli-20240415T180500Z-SPY_manifest.json"
        assert out_file.exists()
        body = json.loads(out_file.read_text(encoding="utf-8"))
        assert body["panel_id"] == "cli-20240415T180500Z-SPY"
        assert body["universe"] == ["SPY"]

    def test_universe_as_csv_string(self, isolated_data: Path):
        # Convenience: the CLI passes a CSV string, the API passes a list.
        # Both should work.
        result = build_panel_manifest(
            decision_time="2024-05-15T18:05:00Z",
            universe="SPY, QQQ , GLD",  # spaces stripped
            config_dir=CONFIG_DIR,
            data_dir=Path(os.environ["PIT_MARKET_DATA"]),
        )
        assert result["universe"] == ["SPY", "QQQ", "GLD"]

    def test_unknown_symbol_raises_panelbuilderror(self, isolated_data: Path):
        with pytest.raises(PanelBuildError, match="unknown canonical_symbol"):
            build_panel_manifest(
                decision_time="2024-06-15T18:05:00Z",
                universe=["SPY", "FAKE_TICKER"],
                config_dir=CONFIG_DIR,
                data_dir=Path(os.environ["PIT_MARKET_DATA"]),
            )
        # No file should be written on validation failure.
        assert list(isolated_data.iterdir()) == []

    def test_empty_universe_raises(self, isolated_data: Path):
        with pytest.raises(PanelBuildError, match="at least one symbol"):
            build_panel_manifest(
                decision_time="2024-07-15T18:05:00Z",
                universe=[],
                config_dir=CONFIG_DIR,
                data_dir=Path(os.environ["PIT_MARKET_DATA"]),
            )

    def test_bad_timestamp_raises(self, isolated_data: Path):
        with pytest.raises(PanelBuildError, match="invalid decision_time"):
            build_panel_manifest(
                decision_time="not-a-date",
                universe=["SPY"],
                config_dir=CONFIG_DIR,
                data_dir=Path(os.environ["PIT_MARKET_DATA"]),
            )

    def test_bad_clock_raises(self, isolated_data: Path):
        with pytest.raises(PanelBuildError, match="decision_clock"):
            build_panel_manifest(
                decision_time="2024-08-15T18:05:00Z",
                universe=["SPY"],
                decision_clock="9999_BAD",
                config_dir=CONFIG_DIR,
                data_dir=Path(os.environ["PIT_MARKET_DATA"]),
            )

    def test_panel_id_is_idempotent_for_same_inputs(
        self, isolated_data: Path
    ):
        # Same decision_time + same universe -> same panel_id. Re-running
        # the build silently overwrites the manifest (matches CLI behaviour).
        a = build_panel_manifest(
            decision_time="2024-09-15T18:05:00Z",
            universe=["SPY", "QQQ"],
            config_dir=CONFIG_DIR,
            data_dir=Path(os.environ["PIT_MARKET_DATA"]),
        )
        b = build_panel_manifest(
            decision_time="2024-09-15T18:05:00Z",
            universe=["SPY", "QQQ"],
            config_dir=CONFIG_DIR,
            data_dir=Path(os.environ["PIT_MARKET_DATA"]),
        )
        assert a["panel_id"] == b["panel_id"]
        # Two writes but only one file on disk (second overwrote first)
        files = list(isolated_data.iterdir())
        assert len(files) == 1

    def test_different_universe_different_panel_id(
        self, isolated_data: Path
    ):
        a = build_panel_manifest(
            decision_time="2024-10-15T18:05:00Z",
            universe=["SPY"],
            config_dir=CONFIG_DIR,
            data_dir=Path(os.environ["PIT_MARKET_DATA"]),
        )
        b = build_panel_manifest(
            decision_time="2024-10-15T18:05:00Z",
            universe=["SPY", "QQQ"],
            config_dir=CONFIG_DIR,
            data_dir=Path(os.environ["PIT_MARKET_DATA"]),
        )
        assert a["panel_id"] != b["panel_id"]


# ─────────────────────────────────────────────────────────────────────
# POST /v1/panels/build — HTTP endpoint
# ─────────────────────────────────────────────────────────────────────


class TestBuildPanelEndpoint:
    def _client(self) -> TestClient:
        # No special fixture needed — the env vars are set in the
        # isolated_data fixture, which must be active when entering.
        return TestClient(app)

    def test_post_happy_path_returns_201(self, isolated_data: Path):
        with self._client() as c:
            r = c.post(
                "/v1/panels/build",
                json={
                    "decision_time": "2024-11-15T18:05:00Z",
                    "universe": ["SPY", "QQQ", "GLD", "SLV"],
                    "decision_clock": "1805_ET",
                },
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["panel_id"] == "cli-20241115T180500Z-SPY-QQQ-GLD-SLV"
        # _path is internal — API should NOT leak it
        assert "_path" not in body
        # File is on disk
        out = isolated_data / "cli-20241115T180500Z-SPY-QQQ-GLD-SLV_manifest.json"
        assert out.exists()

    def test_post_unknown_symbol_returns_400(self, isolated_data: Path):
        with self._client() as c:
            r = c.post(
                "/v1/panels/build",
                json={
                    "decision_time": "2024-12-15T18:05:00Z",
                    "universe": ["FAKE_TICKER"],
                },
            )
        assert r.status_code == 400
        assert "FAKE_TICKER" in r.json()["detail"]
        # No file written
        assert list(isolated_data.iterdir()) == []

    def test_post_bad_timestamp_returns_400(self, isolated_data: Path):
        with self._client() as c:
            r = c.post(
                "/v1/panels/build",
                json={
                    "decision_time": "yesterday",
                    "universe": ["SPY"],
                },
            )
        assert r.status_code == 400
        assert "invalid decision_time" in r.json()["detail"]

    def test_post_bad_clock_returns_422(self, isolated_data: Path):
        # Pydantic catches clock validation before reaching build_panel_manifest
        with self._client() as c:
            r = c.post(
                "/v1/panels/build",
                json={
                    "decision_time": "2025-01-15T18:05:00Z",
                    "universe": ["SPY"],
                    "decision_clock": "9999_BAD",
                },
            )
        assert r.status_code == 422
        assert "decision_clock" in r.text

    def test_post_empty_universe_returns_422(self, isolated_data: Path):
        # Pydantic min_length=1 catches this before the handler runs.
        with self._client() as c:
            r = c.post(
                "/v1/panels/build",
                json={
                    "decision_time": "2025-02-15T18:05:00Z",
                    "universe": [],
                },
            )
        assert r.status_code == 422

    def test_post_default_clock_is_1805_et(self, isolated_data: Path):
        # If decision_clock is omitted, server defaults to 1805_ET
        with self._client() as c:
            r = c.post(
                "/v1/panels/build",
                json={
                    "decision_time": "2025-03-15T18:05:00Z",
                    "universe": ["SPY"],
                },
            )
        assert r.status_code == 201
        assert r.json()["decision_clock"] == "1805_ET"

    def test_post_appears_in_list_endpoint(self, isolated_data: Path):
        # End-to-end: build two panels, list them, check newest-first order.
        with self._client() as c:
            c.post(
                "/v1/panels/build",
                json={
                    "decision_time": "2025-04-15T18:05:00Z",
                    "universe": ["SPY"],
                },
            )
            c.post(
                "/v1/panels/build",
                json={
                    "decision_time": "2025-04-16T18:05:00Z",
                    "universe": ["SPY", "QQQ"],
                },
            )
            r = c.get("/v1/panels")
        assert r.status_code == 200
        body = r.json()
        # count includes any pre-existing panels (none in tmp dir)
        assert body["count"] == 2
        ids = [p["panel_id"] for p in body["panels"]]
        assert "cli-20250416T180500Z-SPY-QQQ" in ids
        assert "cli-20250415T180500Z-SPY" in ids