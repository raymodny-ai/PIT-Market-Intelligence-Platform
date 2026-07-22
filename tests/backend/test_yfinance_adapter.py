"""YFinance Adapter tests — TODO T-05a acceptance.

Uses monkey-patching of yfinance.Ticker to avoid real network calls. Real
integration tests are marked ``slow`` and skipped by default.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pit_market.ingestion.adapters.yfinance import (
    DecisionClock,
    PriceType,
    YFinanceAdapter,
)
from pit_market.storage.registry import Registry

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
TEST_RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw_test"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(CONFIG_DIR)


@pytest.fixture
def tmp_raw_dir(tmp_path) -> Path:
    """Per-test Raw dir; keeps test data isolated."""
    p = tmp_path / "raw"
    p.mkdir()
    return p


@pytest.fixture
def adapter(registry: Registry, tmp_raw_dir: Path) -> YFinanceAdapter:
    return YFinanceAdapter(
        registry=registry,
        raw_dir=tmp_raw_dir,
        rate_limit_per_sec=100.0,  # disable throttle in tests
    )


def _make_yf_df(rows: list[dict]) -> pd.DataFrame:
    """Build a yfinance-style DataFrame from a list of row dicts."""
    df = pd.DataFrame(rows)
    df.index = pd.DatetimeIndex([r["Date"] for r in rows])
    return df


# =============================================================================
# Discipline #8: canonical_symbol hard reject
# =============================================================================


class TestDiscipline:
    def test_unmapped_symbol_rejected(self, adapter: YFinanceAdapter) -> None:
        with pytest.raises(Exception) as excinfo:
            adapter.fetch("FAKE_SYMBOL", "2024-01-02", "2024-01-05")
        assert "UNMAPPED_SYMBOL" in str(excinfo.value) or "FAKE_SYMBOL" in str(excinfo.value)


# =============================================================================
# Calendar guard (T-05a)
# =============================================================================


class TestCalendarGuard:
    def test_weekend_only_range_returns_empty(self, adapter: YFinanceAdapter) -> None:
        # Sat 2024-01-06 to Sun 2024-01-07: no trading days
        obs = adapter.fetch("QQQ", "2024-01-06", "2024-01-07")
        assert obs == []

    def test_holiday_only_range_returns_empty(self, adapter: YFinanceAdapter) -> None:
        # 2024-12-25 (Christmas) only: closed
        obs = adapter.fetch("QQQ", "2024-12-25", "2024-12-25")
        assert obs == []


# =============================================================================
# Raw landing
# =============================================================================


def _mock_ticker(df: pd.DataFrame) -> MagicMock:
    """Build a mock yfinance.Ticker that returns `df` from .history()."""
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df
    return mock_ticker


class TestRawLanding:
    def test_landed_files_exist(self, adapter: YFinanceAdapter, tmp_raw_dir: Path) -> None:
        df = _make_yf_df(
            [
                {
                    "Date": "2024-01-02",
                    "Open": 410.0, "High": 412.0, "Low": 409.0,
                    "Close": 411.0, "Adj Close": 411.0,
                    "Volume": 50000000, "Dividends": 0.0, "Stock Splits": 0.0,
                },
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)) as _:
            obs = adapter.fetch("QQQ", "2024-01-02", "2024-01-02")
        assert obs  # at least one obs

        run_dirs = list(tmp_raw_dir.rglob("run_id=*"))
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]
        assert (run_dir / "request.json").exists()
        assert (run_dir / "response.json.gz").exists()
        assert (run_dir / "response_headers.json").exists()
        assert (run_dir / "manifest.json").exists()

    def test_manifest_quality_status_valid(self, adapter: YFinanceAdapter, tmp_raw_dir: Path) -> None:
        df = _make_yf_df(
            [
                {
                    "Date": "2024-01-02", "Open": 100, "High": 101, "Low": 99,
                    "Close": 100.5, "Adj Close": 100.5, "Volume": 1_000_000,
                    "Dividends": 0.0, "Stock Splits": 0.0,
                },
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            adapter.fetch("QQQ", "2024-01-02", "2024-01-02")
        manifest = json.loads((next(tmp_raw_dir.rglob("manifest.json"))).read_text())
        assert manifest["quality_status"] == "VALID"
        assert manifest["record_count"] == 1
        assert manifest["source_name"] == "yfinance"
        assert manifest["dataset_name"] == "daily_ohlcv"
        assert manifest["decision_clock"] == "1805_ET"

    def test_empty_response_lands_raw_with_status(
        self, adapter: YFinanceAdapter, tmp_raw_dir: Path
    ) -> None:
        empty_df = pd.DataFrame()
        with patch("yfinance.Ticker", return_value=_mock_ticker(empty_df)):
            obs = adapter.fetch("QQQ", "2024-01-02", "2024-01-02")
        assert obs == []
        manifest = json.loads((next(tmp_raw_dir.rglob("manifest.json"))).read_text())
        assert manifest["quality_status"] == "EMPTY_RESPONSE"
        assert manifest["record_count"] == 0


# =============================================================================
# price_type 三态 (T-05a)
# =============================================================================


class TestPriceType:
    def test_raw_close_emitted(self, adapter: YFinanceAdapter) -> None:
        df = _make_yf_df(
            [
                {
                    "Date": "2024-01-02", "Open": 100, "High": 101, "Low": 99,
                    "Close": 100.5, "Adj Close": 100.5, "Volume": 1_000_000,
                    "Dividends": 0.0, "Stock Splits": 0.0,
                },
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            obs = adapter.fetch("QQQ", "2024-01-02", "2024-01-02")
        raw = [o for o in obs if o.price_type == PriceType.RAW_CLOSE and o.field_name == "price__yf__close"]
        assert len(raw) == 1
        assert raw[0].value == 100.5

    def test_adj_close_only_emitted_when_different(self, adapter: YFinanceAdapter) -> None:
        # After a 2:1 split, raw close is 50 but adj close stays 100
        df = _make_yf_df(
            [
                {
                    "Date": "2024-01-02", "Open": 50, "High": 51, "Low": 49,
                    "Close": 50.0, "Adj Close": 100.0, "Volume": 1_000_000,
                    "Dividends": 0.0, "Stock Splits": 0.0,  # yfinance pre-applies splits
                },
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            obs = adapter.fetch("QQQ", "2024-01-02", "2024-01-02")
        adj = [o for o in obs if o.price_type == PriceType.ADJ_CLOSE]
        assert len(adj) == 1
        assert adj[0].value == 100.0

    def test_no_adj_close_when_equal_to_raw(self, adapter: YFinanceAdapter) -> None:
        df = _make_yf_df(
            [
                {
                    "Date": "2024-01-02", "Open": 100, "High": 101, "Low": 99,
                    "Close": 100.0, "Adj Close": 100.0, "Volume": 1_000_000,
                    "Dividends": 0.0, "Stock Splits": 0.0,
                },
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            obs = adapter.fetch("QQQ", "2024-01-02", "2024-01-02")
        adj = [o for o in obs if o.price_type == PriceType.ADJ_CLOSE]
        assert adj == []

    def test_split_factor_emitted(self, adapter: YFinanceAdapter) -> None:
        df = _make_yf_df(
            [
                {
                    "Date": "2024-06-17", "Open": 100, "High": 101, "Low": 99,
                    "Close": 100.0, "Adj Close": 50.0,  # post-2:1 split: raw=100, adj=50
                    "Volume": 1_000_000, "Dividends": 0.0, "Stock Splits": 2.0,
                },
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            obs = adapter.fetch("QQQ", "2024-06-17", "2024-06-17")
        splits = [o for o in obs if o.price_type == PriceType.SPLIT_FACTOR]
        assert len(splits) == 1
        assert splits[0].value == 2.0
        assert splits[0].split_ratio == 2.0

    def test_adj_factor_recorded(self, adapter: YFinanceAdapter) -> None:
        # adj_factor = Adj Close / Close = 100/50 = 2.0
        df = _make_yf_df(
            [
                {
                    "Date": "2024-06-17", "Open": 50, "High": 51, "Low": 49,
                    "Close": 50.0, "Adj Close": 100.0, "Volume": 1_000_000,
                    "Dividends": 0.0, "Stock Splits": 2.0,
                },
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            obs = adapter.fetch("QQQ", "2024-06-17", "2024-06-17")
        raw = [o for o in obs if o.price_type == PriceType.RAW_CLOSE and o.field_name == "price__yf__close"]
        assert raw[0].adj_factor == pytest.approx(2.0)


# =============================================================================
# Decision clock & available_at
# =============================================================================


class TestDecisionClock:
    def test_default_clock_is_1805_et(self, adapter: YFinanceAdapter, tmp_raw_dir: Path) -> None:
        df = _make_yf_df(
            [
                {
                    "Date": "2024-01-02", "Open": 100, "High": 101, "Low": 99,
                    "Close": 100.0, "Adj Close": 100.0, "Volume": 1_000_000,
                    "Dividends": 0.0, "Stock Splits": 0.0,
                },
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            adapter.fetch("QQQ", "2024-01-02", "2024-01-02")
        manifest = json.loads((next(tmp_raw_dir.rglob("manifest.json"))).read_text())
        assert manifest["decision_clock"] == "1805_ET"

    def test_quote_realtime_clock_1605_et(self, adapter: YFinanceAdapter, tmp_raw_dir: Path) -> None:
        df = _make_yf_df(
            [
                {
                    "Date": "2024-01-02", "Open": 100, "High": 101, "Low": 99,
                    "Close": 100.0, "Adj Close": 100.0, "Volume": 1_000_000,
                    "Dividends": 0.0, "Stock Splits": 0.0,
                },
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            adapter.fetch(
                "QQQ", "2024-01-02", "2024-01-02",
                decision_clock=DecisionClock.QUOTE_REALTIME,
            )
        manifest = json.loads((next(tmp_raw_dir.rglob("manifest.json"))).read_text())
        assert manifest["decision_clock"] == "1605_ET"

    def test_available_at_next_business_day_18_et(
        self, adapter: YFinanceAdapter
    ) -> None:
        # Mon 2024-01-08 → next biz day = Tue 2024-01-09 18:00
        df = _make_yf_df(
            [
                {
                    "Date": "2024-01-08", "Open": 100, "High": 101, "Low": 99,
                    "Close": 100.0, "Adj Close": 100.0, "Volume": 1_000_000,
                    "Dividends": 0.0, "Stock Splits": 0.0,
                },
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            obs = adapter.fetch("QQQ", "2024-01-08", "2024-01-08")
        raw = [o for o in obs if o.price_type == PriceType.RAW_CLOSE and o.field_name == "price__yf__close"]
        assert raw[0].available_at == datetime(2024, 1, 9, 18, 0)

    def test_available_at_skips_weekend(
        self, adapter: YFinanceAdapter
    ) -> None:
        # Fri 2024-01-12 → Mon 2024-01-15 is MLK Day → Tue 2024-01-16 18:00
        df = _make_yf_df(
            [
                {
                    "Date": "2024-01-12", "Open": 100, "High": 101, "Low": 99,
                    "Close": 100.0, "Adj Close": 100.0, "Volume": 1_000_000,
                    "Dividends": 0.0, "Stock Splits": 0.0,
                },
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            obs = adapter.fetch("QQQ", "2024-01-12", "2024-01-12")
        raw = [o for o in obs if o.price_type == PriceType.RAW_CLOSE and o.field_name == "price__yf__close"]
        assert raw[0].available_at == datetime(2024, 1, 16, 18, 0)


# =============================================================================
# detect_roll_events (T-05a exposed for T-08 consumption)
# =============================================================================


class TestRollDetection:
    def test_no_roll_for_normal_moves(self, adapter: YFinanceAdapter) -> None:
        # ~1% move is normal
        df = _make_yf_df(
            [
                {"Date": "2024-01-02", "Open": 100, "High": 101, "Low": 99,
                 "Close": 100.0, "Adj Close": 100.0, "Volume": 1_000_000,
                 "Dividends": 0.0, "Stock Splits": 0.0},
                {"Date": "2024-01-03", "Open": 100, "High": 102, "Low": 100,
                 "Close": 101.0, "Adj Close": 101.0, "Volume": 1_000_000,
                 "Dividends": 0.0, "Stock Splits": 0.0},
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            events = adapter.detect_roll_events("GC=F", "2024-01-02", "2024-01-03", gap_threshold_pct=2.0)
        assert events == []

    def test_roll_detected_for_large_gap(self, adapter: YFinanceAdapter) -> None:
        # 5% gap = rollover candidate (threshold 2.0%)
        df = _make_yf_df(
            [
                {"Date": "2024-01-02", "Open": 100, "High": 101, "Low": 99,
                 "Close": 100.0, "Adj Close": 100.0, "Volume": 1_000_000,
                 "Dividends": 0.0, "Stock Splits": 0.0},
                {"Date": "2024-01-03", "Open": 95, "High": 96, "Low": 94,
                 "Close": 95.0, "Adj Close": 95.0, "Volume": 1_000_000,
                 "Dividends": 0.0, "Stock Splits": 0.0},
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            events = adapter.detect_roll_events("GC=F", "2024-01-02", "2024-01-03", gap_threshold_pct=2.0)
        assert len(events) == 1
        assert events[0].canonical_symbol == "GC=F"
        assert events[0].spread == -5.0


# =============================================================================
# Quality flags propagation (discipline #7 prep)
# =============================================================================


class TestQualityFlags:
    def test_decision_clock_in_quality_flags(self, adapter: YFinanceAdapter) -> None:
        df = _make_yf_df(
            [
                {"Date": "2024-01-02", "Open": 100, "High": 101, "Low": 99,
                 "Close": 100.0, "Adj Close": 100.0, "Volume": 1_000_000,
                 "Dividends": 0.0, "Stock Splits": 0.0},
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            obs = adapter.fetch(
                "QQQ", "2024-01-02", "2024-01-02",
                decision_clock=DecisionClock.QUOTE_REALTIME,
            )
        assert all(o.quality_flags.get("decision_clock") == "1605_ET" for o in obs)

    def test_raw_record_hash_present(self, adapter: YFinanceAdapter) -> None:
        df = _make_yf_df(
            [
                {"Date": "2024-01-02", "Open": 100, "High": 101, "Low": 99,
                 "Close": 100.0, "Adj Close": 100.0, "Volume": 1_000_000,
                 "Dividends": 0.0, "Stock Splits": 0.0},
            ]
        )
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            obs = adapter.fetch("QQQ", "2024-01-02", "2024-01-02")
        assert all(len(o.raw_record_hash) == 64 for o in obs)


# =============================================================================
# Rate limit (T-05a: 1 req/s default)
# =============================================================================


class TestRateLimit:
    def test_throttle_respects_interval(self) -> None:
        # Use real throttle (1 req/s); measure elapsed
        import time

        df = _make_yf_df(
            [
                {"Date": "2024-01-02", "Open": 100, "High": 101, "Low": 99,
                 "Close": 100.0, "Adj Close": 100.0, "Volume": 1_000_000,
                 "Dividends": 0.0, "Stock Splits": 0.0},
            ]
        )
        reg = Registry.load(CONFIG_DIR)
        adapter = YFinanceAdapter(registry=reg, raw_dir=Path("/tmp/pit-ratelimit"), rate_limit_per_sec=2.0)

        start = time.monotonic()
        with patch("yfinance.Ticker", return_value=_mock_ticker(df)):
            adapter.fetch("QQQ", "2024-01-02", "2024-01-02")
            adapter.fetch("QQQ", "2024-01-02", "2024-01-02")  # second call: throttled
        elapsed = time.monotonic() - start
        # 2 req/s → min interval 0.5s; first call has no prior → 0 wait;
        # second call waits ~0.5s. Total ≥ 0.4s (allow tiny slop)
        assert elapsed >= 0.4
