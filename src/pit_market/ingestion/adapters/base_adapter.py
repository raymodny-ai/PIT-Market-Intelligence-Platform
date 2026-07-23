"""Base Adapter interface for v2.0 real data pipeline (T-34).

All v2.0 adapters implement this Protocol:
  ``fetch(symbol, start, end, freq) -> pl.DataFrame``

Output schema is standardised:
  {canonical_symbol, date, open, high, low, close, volume, adj_close, source}

Discipline #8: ``available_at`` must be TIMESTAMPTZ minute-precision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import polars as pl

# Standardised output columns for all v2.0 adapters
REAL_DATA_SCHEMA = [
    "canonical_symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adj_close",
    "source",
]


@dataclass(frozen=True)
class FetchResult:
    """Wrapper around the adapter fetch output."""

    df: pl.DataFrame
    source: str
    symbol: str
    row_count: int
    quality_status: str  # VALID | SOURCE_THROTTLED | SOURCE_FAILED | EMPTY_RESPONSE
    quality_flags: dict | None = None


class BaseAdapter(Protocol):
    """Stable interface for v2.0 real data adapters."""

    def fetch(
        self,
        symbol: str,
        start: date,
        end: date,
        freq: str = "1d",
    ) -> FetchResult:
        """Fetch historical OHLCV data for a single symbol.

        Args:
            symbol: canonical_symbol (e.g. 'SPY')
            start: start date (inclusive)
            end: end date (inclusive)
            freq: '1d' | '1h' | '1m'

        Returns:
            FetchResult with standardised DataFrame
        """
        ...


def validate_output_schema(df: pl.DataFrame) -> bool:
    """Check that the DataFrame has the standardised columns."""
    missing = [c for c in REAL_DATA_SCHEMA if c not in df.columns]
    return len(missing) == 0


def check_null_rate(df: pl.DataFrame, threshold: float = 0.001) -> dict[str, float]:
    """Return null rate per column; flag any column exceeding threshold."""
    if df.is_empty():
        return {}
    result = {}
    for col in df.columns:
        null_count = df[col].null_count()
        rate = null_count / df.height
        if rate > threshold:
            result[col] = rate
    return result


def check_price_continuity(df: pl.DataFrame, threshold_pct: float = 50.0) -> list[dict]:
    """Detect anomalous price jumps (> threshold_pct% day-over-day).

    Returns list of anomaly records.
    """
    if df.is_empty() or "close" not in df.columns or df.height < 2:
        return []
    sorted_df = df.sort("date")
    closes = sorted_df["close"].to_list()
    symbols = sorted_df["canonical_symbol"].to_list()
    dates = sorted_df["date"].to_list()
    anomalies = []
    for i in range(1, len(closes)):
        if closes[i - 1] and closes[i - 1] > 0:
            pct = abs(closes[i] - closes[i - 1]) / closes[i - 1] * 100
            if pct >= threshold_pct:
                anomalies.append({
                    "symbol": symbols[i],
                    "date": str(dates[i]),
                    "prev_close": closes[i - 1],
                    "close": closes[i],
                    "pct_change": round(pct, 2),
                })
    return anomalies
