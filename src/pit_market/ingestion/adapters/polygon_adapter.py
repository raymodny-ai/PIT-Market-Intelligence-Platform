"""Polygon REST v2 Historical Aggregates Adapter (T-34).

v2.0 real data pipeline — fetches OHLCV via Polygon.io REST API.

Features:
- Minute / daily frequency
- Pagination: ``next_url`` cursor follow
- API key from ``.env`` POLYGON_API_KEY (discipline #9: no hardcoding)
- Rate limiting: exponential backoff
- Standardised output schema matching ``base_adapter.REAL_DATA_SCHEMA``
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import UTC, date, datetime

import httpx
import polars as pl
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

_POLYGON_BASE_URL = "https://api.polygon.io"

_FREQ_MAP = {
    "1d": ("day", 1),
    "1h": ("hour", 1),
    "1m": ("minute", 1),
}


class PolygonAdapterError(Exception):
    pass


class PolygonAdapter:
    """v2.0 Polygon.io adapter — standardised output for DuckDB storage."""

    def __init__(
        self,
        api_key: str | None = None,
        rate_limit_per_sec: float = 5.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("POLYGON_API_KEY", "")
        if not self._api_key:
            log.warning(
                "POLYGON_API_KEY not set — PolygonAdapter will fail on fetch. "
                "Set it in .env or pass api_key explicitly (discipline #9)."
            )
        self._rate_limit = rate_limit_per_sec
        self._last_request_ts: float = 0.0

    def fetch(
        self,
        symbol: str,
        start: date,
        end: date,
        freq: str = "1d",
    ) -> FetchResult:
        """Fetch OHLCV from Polygon.io, return standardised DataFrame."""
        if not self._api_key:
            return FetchResult(
                df=self._empty_df(),
                source="polygon", symbol=symbol, row_count=0,
                quality_status="SOURCE_FAILED",
                quality_flags={"error": "POLYGON_API_KEY not configured"},
            )

        self._throttle()

        timespan, multiplier = _FREQ_MAP.get(freq, ("day", 1))
        # Polygon uses YYYY-MM-DD format for daily, YYYY-MM-DD for minute too
        from_str = start.strftime("%Y-%m-%d")
        to_str = end.strftime("%Y-%m-%d")

        try:
            all_results = self._fetch_all_pages(
                symbol, from_str, to_str, multiplier, timespan
            )
        except Exception as e:
            log.warning("PolygonAdapter fetch failed for %s: %s", symbol, e)
            return FetchResult(
                df=self._empty_df(),
                source="polygon", symbol=symbol, row_count=0,
                quality_status="SOURCE_FAILED",
                quality_flags={"error": str(e)},
            )

        if not all_results:
            return FetchResult(
                df=self._empty_df(),
                source="polygon", symbol=symbol, row_count=0,
                quality_status="EMPTY_RESPONSE",
            )

        result_df = self._build_standardised_df(symbol, all_results)

        quality_status = "VALID"
        quality_flags: dict = {}

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
            source="polygon",
            symbol=symbol,
            row_count=result_df.height,
            quality_status=quality_status,
            quality_flags=quality_flags or None,
        )

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        min_interval = 1.0 / self._rate_limit
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_ts = time.monotonic()

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _fetch_page(self, url: str, params: dict) -> dict:
        """Fetch a single page from Polygon API."""
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 429:
                # Rate limited — wait and retry
                time.sleep(5)
                resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    def _fetch_all_pages(
        self,
        symbol: str,
        from_str: str,
        to_str: str,
        multiplier: int,
        timespan: str,
    ) -> list[dict]:
        """Follow ``next_url`` cursor to fetch all pages."""
        url = f"{_POLYGON_BASE_URL}/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{from_str}/{to_str}"
        params = {
            "apiKey": self._api_key,
            "limit": 50000,
            "adjusted": "true",
            "sort": "asc",
        }
        all_results: list[dict] = []
        page_count = 0
        max_pages = 100  # safety limit

        while url and page_count < max_pages:
            self._throttle()
            data = self._fetch_page(url, params if page_count == 0 else {"apiKey": self._api_key})
            results = data.get("results", [])
            if not results:
                break
            all_results.extend(results)
            # Follow pagination
            url = data.get("next_url", "")
            page_count += 1
            # After first page, params are embedded in next_url
            params = {"apiKey": self._api_key}

        return all_results

    def _build_standardised_df(self, symbol: str, results: list[dict]) -> pl.DataFrame:
        """Convert Polygon API results to standardised Polars schema."""
        rows = []
        for r in results:
            # Polygon timestamp is in milliseconds
            ts_ms = r.get("t", 0)
            obs_date = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date()
            rows.append({
                "canonical_symbol": symbol,
                "date": obs_date,
                "open": float(r.get("o", 0.0)),
                "high": float(r.get("h", 0.0)),
                "low": float(r.get("l", 0.0)),
                "close": float(r.get("c", 0.0)),
                "volume": float(r.get("v", 0)),
                "adj_close": float(r.get("c", 0.0)),  # Polygon adjusted close ≈ close
                "source": "polygon",
            })
        return pl.DataFrame(rows)

    def _empty_df(self) -> pl.DataFrame:
        return pl.DataFrame(schema={
            "canonical_symbol": pl.Utf8, "date": pl.Date,
            "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
            "close": pl.Float64, "volume": pl.Float64,
            "adj_close": pl.Float64, "source": pl.Utf8,
        })


def compute_data_hash(df: pl.DataFrame) -> str:
    """Deterministic hash for idempotency."""
    content = df.write_json()
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
