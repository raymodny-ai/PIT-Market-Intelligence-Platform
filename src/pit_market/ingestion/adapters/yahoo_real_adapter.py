"""Yahoo Finance Real Data Adapter (T-34).

v2.0 real data pipeline — fetches actual OHLCV via yfinance and outputs
a standardised Polars DataFrame.

Distinction from T-05a: T-05a handles v1.1 manifest-only flow with Raw
landing; T-34 is the v2.0 real data pipeline for DuckDB storage.

Features:
- Rate limiting: 1 req/s + exponential backoff
- Frequency support: 1d / 1h / 1m
- Schema validation + null rate check + price continuity check
- Idempotent: same input → same hash, no re-ingestion
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import date

import polars as pl
import yfinance as yf
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pit_market.ingestion.adapters.base_adapter import (
    FetchResult,
    check_null_rate,
    check_price_continuity,
    validate_output_schema,
)

log = logging.getLogger(__name__)

_FREQ_MAP = {
    "1d": "1d",
    "1h": "1h",
    "1m": "1m",
}


class YahooRealAdapter:
    """v2.0 Yahoo Finance adapter — standardised output for DuckDB storage."""

    def __init__(self, rate_limit_per_sec: float = 1.0) -> None:
        self._rate_limit = rate_limit_per_sec
        self._last_request_ts: float = 0.0

    def fetch(
        self,
        symbol: str,
        start: date,
        end: date,
        freq: str = "1d",
    ) -> FetchResult:
        """Fetch OHLCV from Yahoo Finance, return standardised DataFrame."""
        self._throttle()

        yf_freq = _FREQ_MAP.get(freq, "1d")
        quality_status = "VALID"
        quality_flags: dict = {}

        try:
            df = self._fetch_with_retry(symbol, start, end, yf_freq)
        except Exception as e:
            log.warning("YahooRealAdapter fetch failed for %s: %s", symbol, e)
            return FetchResult(
                df=pl.DataFrame(schema={
                    "canonical_symbol": pl.Utf8, "date": pl.Date,
                    "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                    "close": pl.Float64, "volume": pl.Float64,
                    "adj_close": pl.Float64, "source": pl.Utf8,
                }),
                source="yahoo", symbol=symbol, row_count=0,
                quality_status="SOURCE_FAILED",
                quality_flags={"error": str(e)},
            )

        if df is None or df.empty:
            return FetchResult(
                df=pl.DataFrame(schema={
                    "canonical_symbol": pl.Utf8, "date": pl.Date,
                    "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                    "close": pl.Float64, "volume": pl.Float64,
                    "adj_close": pl.Float64, "source": pl.Utf8,
                }),
                source="yahoo", symbol=symbol, row_count=0,
                quality_status="EMPTY_RESPONSE",
            )

        # Build standardised output
        result_df = self._build_standardised_df(symbol, df)

        # Quality checks
        null_issues = check_null_rate(result_df)
        if null_issues:
            quality_flags["high_null_columns"] = list(null_issues.keys())
            quality_status = "SOURCE_THROTTLED"

        anomalies = check_price_continuity(result_df)
        if anomalies:
            quality_flags["price_anomalies"] = anomalies
            quality_flags["anomaly_count"] = len(anomalies)

        assert validate_output_schema(result_df), "Output schema mismatch"

        return FetchResult(
            df=result_df,
            source="yahoo",
            symbol=symbol,
            row_count=result_df.height,
            quality_status=quality_status,
            quality_flags=quality_flags or None,
        )

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        min_interval = 1.0 / self._rate_limit
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_ts = time.monotonic()

    @retry(
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _fetch_with_retry(self, symbol: str, start: date, end: date, freq: str):
        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start.isoformat(),
            end=(end.isoformat()),
            interval=freq,
            auto_adjust=False,
            actions=False,
            raise_errors=False,
        )
        return df

    def _build_standardised_df(self, symbol: str, raw_df) -> pl.DataFrame:
        """Convert yfinance DataFrame to standardised Polars schema."""
        import pandas as pd

        rows = []
        for ts, row in raw_df.iterrows():
            obs_date = pd.Timestamp(ts).date()
            rows.append({
                "canonical_symbol": symbol,
                "date": obs_date,
                "open": float(row.get("Open", 0.0)) if not pd.isna(row.get("Open")) else None,
                "high": float(row.get("High", 0.0)) if not pd.isna(row.get("High")) else None,
                "low": float(row.get("Low", 0.0)) if not pd.isna(row.get("Low")) else None,
                "close": float(row.get("Close", 0.0)) if not pd.isna(row.get("Close")) else None,
                "volume": float(row.get("Volume", 0)) if not pd.isna(row.get("Volume")) else None,
                "adj_close": float(row.get("Adj Close", row.get("Close", 0.0))) if not pd.isna(row.get("Adj Close", row.get("Close"))) else None,
                "source": "yahoo",
            })
        return pl.DataFrame(rows)


def compute_data_hash(df: pl.DataFrame) -> str:
    """Deterministic hash for idempotency — same input → same hash."""
    content = df.write_json()
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
