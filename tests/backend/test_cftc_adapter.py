"""CFTC COT Adapter tests — TODO T-05c acceptance."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pit_market.ingestion.adapters.cftc_cot import (
    CotCftcAdapter,
    CotReportType,
)
from pit_market.storage.registry import Registry

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(CONFIG_DIR)


@pytest.fixture
def adapter(registry: Registry, tmp_path: Path) -> CotCftcAdapter:
    return CotCftcAdapter(
        registry=registry, raw_dir=tmp_path, rate_limit_per_sec=100.0
    )


def _mock_response(text: str, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.content = text.encode("utf-8")
    return r


# =============================================================================
# Routing: cot_report_type selects parser
# =============================================================================


class TestRouting:
    def test_gold_uses_disaggregated(self, registry: Registry) -> None:
        assert registry.instruments["GOLD_COMEX"].cot_report_type == "DISAGGREGATED"
        assert registry.instruments["GLD"].cot_report_type == "DISAGGREGATED"
        assert registry.instruments["IAU"].cot_report_type == "DISAGGREGATED"
        assert registry.instruments["GC=F"].cot_report_type == "DISAGGREGATED"

    def test_silver_uses_disaggregated(self, registry: Registry) -> None:
        assert registry.instruments["SILVER_COMEX"].cot_report_type == "DISAGGREGATED"
        assert registry.instruments["SI=F"].cot_report_type == "DISAGGREGATED"

    @patch("httpx.Client.get")
    def test_disagg_url_used(self, mock_get, adapter: CotCftcAdapter) -> None:
        # Return empty CSV header
        mock_get.return_value = _mock_response(
            "As of Date in Form YYYY-MM-DD,CFTC Contract Market Code,Open Interest All\n"
        )
        adapter.fetch_year(2024, report_type=CotReportType.DISAGGREGATED)
        url = mock_get.call_args.args[0]
        assert "disagg_cot" in url

    @patch("httpx.Client.get")
    def test_legacy_url_used(self, mock_get, adapter: CotCftcAdapter) -> None:
        mock_get.return_value = _mock_response(
            "As of Date in Form YYYY-MM-DD,CFTC Contract Market Code,Open Interest All\n"
        )
        adapter.fetch_year(2024, report_type=CotReportType.LEGACY)
        url = mock_get.call_args.args[0]
        assert "cot_year" in url

    @patch("httpx.Client.get")
    def test_tff_url_used(self, mock_get, adapter: CotCftcAdapter) -> None:
        mock_get.return_value = _mock_response(
            "As of Date in Form YYYY-MM-DD,CFTC Contract Market Code,Open Interest All\n"
        )
        adapter.fetch_year(2024, report_type=CotReportType.TFF)
        url = mock_get.call_args.args[0]
        assert "fina_cot" in url


# =============================================================================
# PIT: available_at = Friday 15:30 ET
# =============================================================================


class TestPitTiming:
    @patch("httpx.Client.get")
    def test_friday_release_at(self, mock_get, adapter: CotCftcAdapter) -> None:
        # Mock minimal Disagg report
        csv = (
            "As of Date in Form YYYY-MM-DD,CFTC Contract Market Code,"
            "Managed Money Long All,Managed Money Short All,Open Interest All\n"
            "2024-01-09,088691,100000,50000,250000\n"
        )
        mock_get.return_value = _mock_response(csv)
        obs = adapter.fetch_year(2024, report_type=CotReportType.DISAGGREGATED, market_code="088691")
        assert len(obs) >= 1
        # Tuesday 2024-01-09 → Friday 2024-01-12 15:30
        assert obs[0].observation_time == datetime(2024, 1, 9, 21, 0)
        assert obs[0].available_at == datetime(2024, 1, 12, 15, 30)

    def test_friday_release_at_holiday_shift(self, adapter: CotCftcAdapter) -> None:
        # 2026-07-04 is Saturday; NYSE observes Independence Day on Fri 2026-07-03.
        # Tuesday 2026-06-30 → Friday 2026-07-03 is a holiday → next biz = Mon 2026-07-06
        fri = adapter._friday_release_at(date(2026, 6, 30))
        assert fri.date() == date(2026, 7, 6)
        assert fri.hour == 15 and fri.minute == 30


# =============================================================================
# Field mapping: managed_money_net
# =============================================================================


class TestFieldMapping:
    @patch("httpx.Client.get")
    def test_managed_money_net_computed(self, mock_get, adapter: CotCftcAdapter) -> None:
        csv = (
            "As of Date in Form YYYY-MM-DD,CFTC Contract Market Code,"
            "Managed Money Long All,Managed Money Short All,Open Interest All\n"
            "2024-01-09,088691,100000,50000,250000\n"
        )
        mock_get.return_value = _mock_response(csv)
        obs = adapter.fetch_year(2024, report_type=CotReportType.DISAGGREGATED, market_code="088691")
        managed = [o for o in obs if o.field_name == "position__cftc__managed_money_net"]
        assert len(managed) >= 1
        assert managed[0].value == 50000.0  # 100000 - 50000

    @patch("httpx.Client.get")
    def test_open_interest_field(self, mock_get, adapter: CotCftcAdapter) -> None:
        csv = (
            "As of Date in Form YYYY-MM-DD,CFTC Contract Market Code,"
            "Open Interest All\n"
            "2024-01-09,088691,250000\n"
        )
        mock_get.return_value = _mock_response(csv)
        obs = adapter.fetch_year(2024, report_type=CotReportType.DISAGGREGATED, market_code="088691")
        oi = [o for o in obs if o.field_name == "position__cftc__open_interest_all"]
        assert len(oi) >= 1
        assert oi[0].value == 250000.0


# =============================================================================
# Market code routing
# =============================================================================


class TestMarketCode:
    def test_gold_market_code(self, adapter: CotCftcAdapter) -> None:
        assert adapter._find_canonical_for_market("088691") in {"GOLD_COMEX", "GLD", "IAU", "GC=F"}

    def test_silver_market_code(self, adapter: CotCftcAdapter) -> None:
        assert adapter._find_canonical_for_market("084691") in {"SILVER_COMEX", "SLV", "SI=F"}

    def test_unknown_market_code(self, adapter: CotCftcAdapter) -> None:
        assert adapter._find_canonical_for_market("999999") is None


# =============================================================================
# Source failure handling
# =============================================================================


class TestFailureHandling:
    @patch("httpx.Client.get", side_effect=Exception("timeout"))
    def test_source_failed(self, mock_get, adapter: CotCftcAdapter, tmp_path: Path) -> None:
        obs = adapter.fetch_year(2024, report_type=CotReportType.DISAGGREGATED, market_code="088691")
        assert obs == []
        manifest = json.loads((next(tmp_path.rglob("manifest.json"))).read_text())
        assert manifest["quality_status"] == "SOURCE_FAILED"
