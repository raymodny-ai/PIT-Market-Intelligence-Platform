"""FINRA Reg SHO Adapter tests — TODO T-05d acceptance."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pit_market.ingestion.adapters.finra_regsho import (
    FinraRegShoAdapter,
)
from pit_market.storage.registry import Registry

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(CONFIG_DIR)


@pytest.fixture
def adapter(registry: Registry, tmp_path: Path) -> FinraRegShoAdapter:
    return FinraRegShoAdapter(registry=registry, raw_dir=tmp_path, rate_limit_per_sec=100.0)


def _mock_response(payload, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.content = json.dumps(payload).encode("utf-8")
    r.json.return_value = payload
    return r


# =============================================================================
# Discipline: T+1 14:00 ET
# =============================================================================


class TestPitTiming:
    @patch("httpx.Client.get")
    def test_available_at_t_plus_1_14_et(self, mock_get, adapter: FinraRegShoAdapter) -> None:
        mock_get.return_value = _mock_response([
            {"symbolCode": "QQQ", "shortVolume": 1000000, "totalVolume": 5000000}
        ])
        obs = adapter.fetch_day(date(2024, 1, 8))  # Monday
        # Mon → next biz = Tue 2024-01-09 14:00
        assert all(o.available_at == datetime(2024, 1, 9, 14, 0) for o in obs)

    @patch("httpx.Client.get")
    def test_t_plus_1_skips_mlk_day(self, mock_get, adapter: FinraRegShoAdapter) -> None:
        # Fri 2024-01-12 → next biz = Tue 2024-01-16 (Mon is MLK Day)
        mock_get.return_value = _mock_response([
            {"symbolCode": "QQQ", "shortVolume": 1000000, "totalVolume": 5000000}
        ])
        obs = adapter.fetch_day(date(2024, 1, 12))
        assert all(o.available_at == datetime(2024, 1, 16, 14, 0) for o in obs)

    @patch("httpx.Client.get")
    def test_observation_time_is_obs_date_16_et(self, mock_get, adapter: FinraRegShoAdapter) -> None:
        mock_get.return_value = _mock_response([
            {"symbolCode": "QQQ", "shortVolume": 1000000, "totalVolume": 5000000}
        ])
        obs = adapter.fetch_day(date(2024, 1, 8))
        assert all(o.observation_time == datetime(2024, 1, 8, 16, 0) for o in obs)


# =============================================================================
# Discipline #7: semantic_warning propagation
# =============================================================================


class TestSemanticWarning:
    @patch("httpx.Client.get")
    def test_short_ratio_has_non_full_market_warning(
        self, mock_get, adapter: FinraRegShoAdapter
    ) -> None:
        mock_get.return_value = _mock_response([
            {"symbolCode": "QQQ", "shortVolume": 1000000, "totalVolume": 5000000}
        ])
        obs = adapter.fetch_day(date(2024, 1, 8))
        ratios = [o for o in obs if o.field_name == "flow__finra__short_ratio"]
        assert len(ratios) >= 1
        assert "非全市场" in ratios[0].semantic_caveat or "consolidated" in ratios[0].semantic_caveat.lower()

    @patch("httpx.Client.get")
    def test_short_volume_not_short_interest_warning(
        self, mock_get, adapter: FinraRegShoAdapter
    ) -> None:
        mock_get.return_value = _mock_response([
            {"symbolCode": "QQQ", "shortVolume": 1000000, "totalVolume": 5000000}
        ])
        obs = adapter.fetch_day(date(2024, 1, 8))
        short_vol = [o for o in obs if o.field_name == "flow__finra__short_volume"]
        assert len(short_vol) >= 1
        assert "short interest" in short_vol[0].semantic_caveat.lower()


# =============================================================================
# Multi-source denominator discipline #8
# =============================================================================


class TestMultiSourceDiscipline:
    @patch("httpx.Client.get")
    def test_short_ratio_uses_finra_only(self, mock_get, adapter: FinraRegShoAdapter) -> None:
        """T-22 rule 6: short_ratio must be same-source (FINRA / FINRA)."""
        mock_get.return_value = _mock_response([
            {"symbolCode": "QQQ", "shortVolume": 1000000, "totalVolume": 5000000}
        ])
        obs = adapter.fetch_day(date(2024, 1, 8))
        ratios = [o for o in obs if o.field_name == "flow__finra__short_ratio"]
        assert len(ratios) == 1
        assert abs(ratios[0].value - 0.2) < 1e-9  # 1000000/5000000


# =============================================================================
# Universe filtering
# =============================================================================


class TestUniverseFilter:
    @patch("httpx.Client.get")
    def test_unknown_symbol_skipped(self, mock_get, adapter: FinraRegShoAdapter) -> None:
        mock_get.return_value = _mock_response([
            {"symbolCode": "QQQ", "shortVolume": 1000000, "totalVolume": 5000000},
            {"symbolCode": "ZZZZZ", "shortVolume": 999, "totalVolume": 1000},  # unknown
        ])
        obs = adapter.fetch_day(date(2024, 1, 8))
        assert all(o.canonical_symbol != "ZZZZZ" for o in obs)
        assert any(o.canonical_symbol == "QQQ" for o in obs)


# =============================================================================
# Failure handling
# =============================================================================


class TestFailureHandling:
    @patch("httpx.Client.get", side_effect=httpx.ConnectError("refused"))
    def test_source_failed(self, mock_get, adapter: FinraRegShoAdapter, tmp_path: Path) -> None:
        obs = adapter.fetch_day(date(2024, 1, 8))
        assert obs == []
        manifest = json.loads((next(tmp_path.rglob("manifest.json"))).read_text())
        assert manifest["quality_status"] == "SOURCE_FAILED"

    @patch("httpx.Client.get")
    def test_empty_response(self, mock_get, adapter: FinraRegShoAdapter, tmp_path: Path) -> None:
        mock_get.return_value = _mock_response([])
        obs = adapter.fetch_day(date(2024, 1, 8))
        assert obs == []
        manifest = json.loads((next(tmp_path.rglob("manifest.json"))).read_text())
        assert manifest["quality_status"] == "EMPTY_RESPONSE"
