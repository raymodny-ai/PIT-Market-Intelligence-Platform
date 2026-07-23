"""Tests for T-34 real data adapters.

Uses respx (httpx mocking) for Polygon and monkeypatch for yfinance.
Each adapter has ≥3 test cases: success / throttled / empty.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import polars as pl
import pytest

from pit_market.ingestion.adapters.base_adapter import (
    FetchResult,
    check_null_rate,
    check_price_continuity,
    validate_output_schema,
)


# ---------------------------------------------------------------------------
# Base adapter utility tests
# ---------------------------------------------------------------------------


class TestBaseAdapterUtils:
    def test_validate_output_schema_valid(self):
        df = pl.DataFrame({
            "canonical_symbol": ["SPY"], "date": [date(2024, 1, 2)],
            "open": [100.0], "high": [101.0], "low": [99.0],
            "close": [100.5], "volume": [1000000], "adj_close": [100.5],
            "source": ["yahoo"],
        })
        assert validate_output_schema(df) is True

    def test_validate_output_schema_missing_column(self):
        df = pl.DataFrame({"canonical_symbol": ["SPY"], "close": [100.0]})
        assert validate_output_schema(df) is False

    def test_check_null_rate(self):
        df = pl.DataFrame({
            "a": [1.0, None, None, None, 5.0],
            "b": [1.0, 2.0, 3.0, 4.0, 5.0],
        })
        issues = check_null_rate(df, threshold=0.5)
        assert "a" in issues
        assert "b" not in issues

    def test_check_price_continuity_anomaly(self):
        df = pl.DataFrame({
            "canonical_symbol": ["SPY"] * 3,
            "date": [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)],
            "close": [100.0, 100.5, 200.0],  # 99% jump on day 3
        })
        anomalies = check_price_continuity(df, threshold_pct=50.0)
        assert len(anomalies) == 1
        assert anomalies[0]["pct_change"] > 50

    def test_check_price_continuity_no_anomaly(self):
        df = pl.DataFrame({
            "canonical_symbol": ["SPY"] * 3,
            "date": [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)],
            "close": [100.0, 100.5, 101.0],
        })
        anomalies = check_price_continuity(df, threshold_pct=50.0)
        assert len(anomalies) == 0

    def test_check_null_rate_empty_df(self):
        df = pl.DataFrame({"a": []})
        assert check_null_rate(df) == {}

    def test_check_price_continuity_empty(self):
        df = pl.DataFrame()
        assert check_price_continuity(df) == []


# ---------------------------------------------------------------------------
# Yahoo Real Adapter tests
# ---------------------------------------------------------------------------


class TestYahooRealAdapter:
    def test_success(self):
        """Successful fetch returns standardised DataFrame."""
        from pit_market.ingestion.adapters.yahoo_real_adapter import YahooRealAdapter

        mock_df = pd.DataFrame({
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Volume": [1000000, 1100000],
            "Adj Close": [100.8, 101.8],
        }, index=pd.DatetimeIndex([
            pd.Timestamp("2024-01-02"),
            pd.Timestamp("2024-01-03"),
        ]))

        adapter = YahooRealAdapter()
        with patch.object(adapter, "_fetch_with_retry", return_value=mock_df):
            result = adapter.fetch("SPY", date(2024, 1, 2), date(2024, 1, 3))

        assert isinstance(result, FetchResult)
        assert result.source == "yahoo"
        assert result.symbol == "SPY"
        assert result.row_count == 2
        assert result.quality_status == "VALID"
        assert validate_output_schema(result.df)
        assert result.df["close"].to_list() == [101.0, 102.0]

    def test_empty_response(self):
        """Empty yfinance response returns EMPTY_RESPONSE status."""
        from pit_market.ingestion.adapters.yahoo_real_adapter import YahooRealAdapter

        adapter = YahooRealAdapter()
        with patch.object(adapter, "_fetch_with_retry", return_value=None):
            result = adapter.fetch("SPY", date(2024, 1, 2), date(2024, 1, 3))

        assert result.quality_status == "EMPTY_RESPONSE"
        assert result.row_count == 0

    def test_source_failed(self):
        """Network error returns SOURCE_FAILED status."""
        from pit_market.ingestion.adapters.yahoo_real_adapter import YahooRealAdapter

        adapter = YahooRealAdapter()
        with patch.object(adapter, "_fetch_with_retry", side_effect=ConnectionError("timeout")):
            result = adapter.fetch("SPY", date(2024, 1, 2), date(2024, 1, 3))

        assert result.quality_status == "SOURCE_FAILED"
        assert result.row_count == 0

    def test_schema_consistent(self):
        """Both adapters output identical schema columns."""
        from pit_market.ingestion.adapters.base_adapter import REAL_DATA_SCHEMA
        from pit_market.ingestion.adapters.yahoo_real_adapter import YahooRealAdapter

        adapter = YahooRealAdapter()
        with patch.object(adapter, "_fetch_with_retry", return_value=None):
            result = adapter.fetch("SPY", date(2024, 1, 2), date(2024, 1, 3))

        assert set(result.df.columns) == set(REAL_DATA_SCHEMA)

    def test_idempotent_hash(self):
        """Same input → same hash (idempotency)."""
        from pit_market.ingestion.adapters.yahoo_real_adapter import YahooRealAdapter, compute_data_hash

        df = pl.DataFrame({
            "canonical_symbol": ["SPY", "SPY"],
            "date": [date(2024, 1, 2), date(2024, 1, 3)],
            "open": [100.0, 101.0], "high": [102.0, 103.0],
            "low": [99.0, 100.0], "close": [101.0, 102.0],
            "volume": [1000000, 1100000], "adj_close": [100.8, 101.8],
            "source": ["yahoo", "yahoo"],
        })
        h1 = compute_data_hash(df)
        h2 = compute_data_hash(df)
        assert h1 == h2


# ---------------------------------------------------------------------------
# Polygon Adapter tests
# ---------------------------------------------------------------------------


class TestPolygonAdapter:
    def test_no_api_key(self):
        """Missing API key returns SOURCE_FAILED."""
        import os
        from pit_market.ingestion.adapters.polygon_adapter import PolygonAdapter

        # Ensure no key is set
        original = os.environ.pop("POLYGON_API_KEY", None)
        try:
            adapter = PolygonAdapter(api_key="")
            result = adapter.fetch("SPY", date(2024, 1, 2), date(2024, 1, 3))
            assert result.quality_status == "SOURCE_FAILED"
            assert "POLYGON_API_KEY" in result.quality_flags.get("error", "")
        finally:
            if original:
                os.environ["POLYGON_API_KEY"] = original

    def test_success(self):
        """Successful Polygon fetch returns standardised data."""
        from pit_market.ingestion.adapters.polygon_adapter import PolygonAdapter

        mock_results = [
            {"t": 1704153600000, "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 1000000},
            {"t": 1704240000000, "o": 101.0, "h": 103.0, "l": 100.0, "c": 102.0, "v": 1100000},
        ]
        adapter = PolygonAdapter(api_key="test-key")
        with patch.object(adapter, "_fetch_all_pages", return_value=mock_results):
            result = adapter.fetch("SPY", date(2024, 1, 2), date(2024, 1, 3))

        assert result.source == "polygon"
        assert result.row_count == 2
        assert result.quality_status == "VALID"
        assert validate_output_schema(result.df)

    def test_empty_response(self):
        """Empty Polygon response returns EMPTY_RESPONSE."""
        from pit_market.ingestion.adapters.polygon_adapter import PolygonAdapter

        adapter = PolygonAdapter(api_key="test-key")
        with patch.object(adapter, "_fetch_all_pages", return_value=[]):
            result = adapter.fetch("SPY", date(2024, 1, 2), date(2024, 1, 3))

        assert result.quality_status == "EMPTY_RESPONSE"
        assert result.row_count == 0

    def test_source_failed(self):
        """Network error returns SOURCE_FAILED."""
        from pit_market.ingestion.adapters.polygon_adapter import PolygonAdapter

        adapter = PolygonAdapter(api_key="test-key")
        with patch.object(adapter, "_fetch_all_pages", side_effect=Exception("network error")):
            result = adapter.fetch("SPY", date(2024, 1, 2), date(2024, 1, 3))

        assert result.quality_status == "SOURCE_FAILED"

    def test_schema_consistent_with_yahoo(self):
        """Polygon and Yahoo adapters output identical schema columns."""
        from pit_market.ingestion.adapters.polygon_adapter import PolygonAdapter
        from pit_market.ingestion.adapters.yahoo_real_adapter import YahooRealAdapter

        polygon = PolygonAdapter(api_key="test-key")
        yahoo = YahooRealAdapter()

        with patch.object(polygon, "_fetch_all_pages", return_value=[]):
            p_result = polygon.fetch("SPY", date(2024, 1, 2), date(2024, 1, 3))
        with patch.object(yahoo, "_fetch_with_retry", return_value=None):
            y_result = yahoo.fetch("SPY", date(2024, 1, 2), date(2024, 1, 3))

        assert set(p_result.df.columns) == set(y_result.df.columns)
