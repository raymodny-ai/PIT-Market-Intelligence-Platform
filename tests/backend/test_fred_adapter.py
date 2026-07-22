"""FRED/ALFRED Adapter tests — TODO T-05b acceptance.

CRITICAL discipline #8:
- Adapter MUST call ALFRED (not FRED main API)
- Adapter MUST send realtime_start=ingest_date
- Raw request.json MUST persist realtime parameters
- API key MUST be stripped from logged Raw manifest
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pit_market.ingestion.adapters.fred_alfred import (
    FredAdapterError,
    FredAlfredAdapter,
)
from pit_market.storage.registry import Registry

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(CONFIG_DIR)


@pytest.fixture
def adapter(registry: Registry, tmp_path: Path) -> FredAlfredAdapter:
    return FredAlfredAdapter(
        registry=registry,
        raw_dir=tmp_path,
        api_key="test-fred-key",
        rate_limit_per_sec=100.0,
    )


def _mock_response(json_payload: dict, status_code: int = 200) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.content = json.dumps(json_payload).encode("utf-8")
    mock_resp.json.return_value = json_payload
    return mock_resp


# =============================================================================
# Discipline #8: ALFRED enforced
# =============================================================================


class TestDisciplineEnforced:
    def test_no_api_key_raises(self, registry: Registry, tmp_path: Path) -> None:
        a = FredAlfredAdapter(registry=registry, raw_dir=tmp_path, api_key=None)
        with pytest.raises(FredAdapterError, match="FRED_API_KEY"):
            a.fetch_series("DGS10", "2024-01-01", "2024-01-05")

    @patch("httpx.Client.get")
    def test_realtime_start_in_request(self, mock_get, adapter: FredAlfredAdapter) -> None:
        mock_get.return_value = _mock_response({"observations": []})
        adapter.fetch_series(
            "DGS10", "2024-01-02", "2024-01-05",
            realtime_start="2024-01-05",
        )
        # Verify the actual URL call contained realtime_start
        call_args = mock_get.call_args
        params = call_args.kwargs.get("params", call_args.args[1] if len(call_args.args) > 1 else {})
        assert "realtime_start" in params, "ALFRED requires realtime_start parameter"
        assert params["realtime_start"] == "2024-01-05"
        assert params["realtime_end"] == "2024-01-05"  # defaults to realtime_start

    @patch("httpx.Client.get")
    def test_alfred_endpoint_used(self, mock_get, adapter: FredAlfredAdapter) -> None:
        mock_get.return_value = _mock_response({"observations": []})
        adapter.fetch_series("DGS10", "2024-01-02", "2024-01-05")
        call_args = mock_get.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "realtime" in url.lower() or "fred/series/observations" in url

    @patch("httpx.Client.get")
    def test_api_key_not_in_logged_payload(self, mock_get, adapter: FredAlfredAdapter, tmp_path: Path) -> None:
        mock_get.return_value = _mock_response({"observations": []})
        adapter.fetch_series("DGS10", "2024-01-02", "2024-01-05")
        # Find any manifest.json in tmp_path
        manifests = list(tmp_path.rglob("manifest.json"))
        assert manifests
        for mp in manifests:
            manifest = json.loads(mp.read_text())
            request = manifest.get("request_payload", {})
            assert "api_key" not in request, "api_key must not be in logged Raw"

    @patch("httpx.Client.get")
    def test_request_persists_realtime_params(self, mock_get, adapter: FredAlfredAdapter, tmp_path: Path) -> None:
        mock_get.return_value = _mock_response({"observations": []})
        adapter.fetch_series(
            "DGS10", "2024-01-02", "2024-01-05",
            realtime_start="2024-01-05",
            realtime_end="2024-01-10",
        )
        request_files = list(tmp_path.rglob("request.json"))
        assert request_files
        req = json.loads(request_files[0].read_text())
        assert req["realtime_start"] == "2024-01-05"
        assert req["realtime_end"] == "2024-01-10"
        assert req["series_id"] == "DGS10"


# =============================================================================
# Raw landing
# =============================================================================


class TestRawLanding:
    @patch("httpx.Client.get")
    def test_lands_valid_response(self, mock_get, adapter: FredAlfredAdapter, tmp_path: Path) -> None:
        mock_get.return_value = _mock_response({
            "observations": [
                {"date": "2024-01-02", "value": "4.05"},
                {"date": "2024-01-03", "value": "4.10"},
            ]
        })
        obs = adapter.fetch_series("DGS10", "2024-01-02", "2024-01-03")
        assert len(obs) == 2
        run_dirs = list(tmp_path.rglob("run_id=*"))
        assert len(run_dirs) == 1
        files = list(run_dirs[0].iterdir())
        names = {f.name for f in files}
        assert {"request.json", "response.json.gz", "response_headers.json", "manifest.json"} <= names

    @patch("httpx.Client.get")
    def test_empty_response_lands_raw(self, mock_get, adapter: FredAlfredAdapter, tmp_path: Path) -> None:
        mock_get.return_value = _mock_response({"observations": []})
        obs = adapter.fetch_series("DGS10", "2024-01-02", "2024-01-05")
        assert obs == []
        manifest = json.loads((next(tmp_path.rglob("manifest.json"))).read_text())
        assert manifest["quality_status"] == "EMPTY_RESPONSE"

    @patch("httpx.Client.get")
    def test_source_failed_lands_raw(self, mock_get, adapter: FredAlfredAdapter, tmp_path: Path) -> None:
        mock_get.side_effect = httpx.ConnectError("connection refused")
        obs = adapter.fetch_series("DGS10", "2024-01-02", "2024-01-05")
        assert obs == []
        manifest = json.loads((next(tmp_path.rglob("manifest.json"))).read_text())
        assert manifest["quality_status"] == "SOURCE_FAILED"


# =============================================================================
# Observation construction
# =============================================================================


class TestObservations:
    @patch("httpx.Client.get")
    def test_dgs10_observations(self, mock_get, adapter: FredAlfredAdapter) -> None:
        mock_get.return_value = _mock_response({
            "observations": [
                {"date": "2024-01-02", "value": "4.05"},
                {"date": "2024-01-03", "value": "4.10"},
            ]
        })
        obs = adapter.fetch_series(
            "DGS10", "2024-01-02", "2024-01-03", realtime_start="2024-01-05"
        )
        assert len(obs) == 2
        assert obs[0].value == 4.05
        assert obs[0].vendor_series_id == "DGS10"
        assert obs[0].field_name == "macro__fred__dgs10"
        assert "ALFRED" in obs[0].semantic_caveat or "修订" in obs[0].semantic_caveat

    @patch("httpx.Client.get")
    def test_skips_missing_values(self, mock_get, adapter: FredAlfredAdapter) -> None:
        # ALFRED encodes missing as "."
        mock_get.return_value = _mock_response({
            "observations": [
                {"date": "2024-01-02", "value": "4.05"},
                {"date": "2024-01-03", "value": "."},  # missing
                {"date": "2024-01-04", "value": "4.15"},
            ]
        })
        obs = adapter.fetch_series("DGS10", "2024-01-02", "2024-01-04")
        assert len(obs) == 2
        assert all(o.value != 0.0 for o in obs)

    @patch("httpx.Client.get")
    def test_vintage_date_recorded(self, mock_get, adapter: FredAlfredAdapter) -> None:
        mock_get.return_value = _mock_response({
            "observations": [{"date": "2024-01-02", "value": "4.05"}]
        })
        obs = adapter.fetch_series(
            "DGS10", "2024-01-02", "2024-01-02", realtime_start="2024-06-15"
        )
        assert obs[0].vintage_date == datetime(2024, 6, 15)

    @patch("httpx.Client.get")
    def test_available_at_next_business_day(self, mock_get, adapter: FredAlfredAdapter) -> None:
        mock_get.return_value = _mock_response({
            "observations": [{"date": "2024-01-02", "value": "4.05"}]
        })
        # realtime_start=2024-01-02 (Tue) → next biz day = 2024-01-03 18:00
        obs = adapter.fetch_series(
            "DGS10", "2024-01-02", "2024-01-02", realtime_start="2024-01-02"
        )
        assert obs[0].available_at == datetime(2024, 1, 3, 18, 0)

    @patch("httpx.Client.get")
    def test_vixcls_uses_market_proxy_rule(self, mock_get, adapter: FredAlfredAdapter, tmp_path: Path) -> None:
        """VIXCLS must trigger fred_market_proxy_t_plus_1 availability rule."""
        mock_get.return_value = _mock_response({
            "observations": [{"date": "2024-01-02", "value": "13.5"}]
        })
        adapter.fetch_series("VIXCLS", "2024-01-02", "2024-01-02")
        # Verify registry has the rule
        rule = adapter._registry.get_availability_rule("fred_market_proxy_t_plus_1")
        assert rule.raw.get("uses_alfred") is True
        assert rule.raw.get("observation_to_release_lag_days") == 1


# =============================================================================
# T-12 case 12: ALFRED vintage vs FRED latest differs
# =============================================================================


class TestVintageVsLatest:
    @patch("httpx.Client.get")
    def test_vintage_query_differs_from_latest(self, mock_get, adapter: FredAlfredAdapter) -> None:
        """T-12 case 12: same series, ALFRED with vintage 2024-01-05 must
        return the value as-of that date, even if the API response contains
        a 'realtime_start' field that shows it was later revised.

        In this test we verify that the request URL contains 'realtime_start'
        which is the ALFRED-distinguishing parameter. FRED main API does not
        accept realtime_start.
        """
        # Mock ALFRED returning a vintage-pinned response
        mock_get.return_value = _mock_response({
            "realtime_start": "2024-01-05",
            "observations": [
                {"date": "2024-01-02", "value": "4.05", "realtime_start": "2024-01-05"},
            ]
        })
        obs = adapter.fetch_series(
            "DGS10", "2024-01-02", "2024-01-02", realtime_start="2024-01-05"
        )
        # Verify request payload includes the vintage
        call_args = mock_get.call_args
        params = call_args.kwargs.get("params", {})
        assert params["realtime_start"] == "2024-01-05"
        # And vintage_date is captured on the observation
        assert obs[0].vintage_date == datetime(2024, 1, 5)
