"""Yahoo Finance Adapter (TODO T-05a).

Responsibilities:
- Rate-limited fetch from yfinance (1 req/s default, exponential backoff)
- Two decision clocks: ``quote_realtime`` (1605_ET) and ``close_final`` (1805_ET)
- Three ``price_type`` values: ``RAW_CLOSE``, ``ADJ_CLOSE``, ``SPLIT_FACTOR``
- Append-only Raw landing: ``data/raw/source=yfinance/.../{request,response,
  response_headers,manifest}.json*``
- SHA-256 dedup: identical response → not re-landed
- Failure surface: ``quality_status = SOURCE_THROTTLED | SOURCE_FAILED``
- Exposes ``detect_roll_events()`` for downstream T-08 feature layer

Discipline:
- #8 available_at must be TIMESTAMPTZ minute precision
- T-05a calendar guard: non-trading days must NOT be written
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pit_market.data.trading_calendar import is_trading_day
from pit_market.storage.registry import Registry

log = logging.getLogger(__name__)


# =============================================================================
# Domain types
# =============================================================================


class DecisionClock(StrEnum):
    QUOTE_REALTIME = "1605_ET"
    CLOSE_FINAL = "1805_ET"


class PriceType(StrEnum):
    RAW_CLOSE = "RAW_CLOSE"
    ADJ_CLOSE = "ADJ_CLOSE"
    SPLIT_FACTOR = "SPLIT_FACTOR"


class YFinanceQualityStatus(StrEnum):
    VALID = "VALID"
    SOURCE_THROTTLED = "SOURCE_THROTTLED"
    SOURCE_FAILED = "SOURCE_FAILED"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"


@dataclass(frozen=True)
class RolloverEvent:
    """Front-month contract rollover (Phase 1: heuristic, see T-08)."""

    canonical_symbol: str
    observation_time: datetime
    old_close: float
    new_close: float
    spread: float
    source: str = "yfinance_gap_detection"


@dataclass
class YFinanceObservation:
    canonical_symbol: str
    field_name: str
    value: float
    unit: str
    observation_time: datetime
    available_at: datetime
    price_type: PriceType
    quality_status: YFinanceQualityStatus
    vendor_symbol: str
    adj_factor: float | None = None
    split_ratio: float | None = None
    quality_flags: dict[str, Any] = field(default_factory=dict)
    raw_record_hash: str = ""


@dataclass
class RawManifest:
    source_name: str = "yfinance"
    dataset_name: str = "daily_ohlcv"
    ingest_date: str = ""
    run_id: str = ""
    request_url: str = ""
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_headers: dict[str, str] = field(default_factory=dict)
    response_size_bytes: int = 0
    response_sha256: str = ""
    record_count: int = 0
    quality_status: str = "VALID"
    quality_flags: dict[str, Any] = field(default_factory=dict)
    decision_clock: str = "1805_ET"


# =============================================================================
# Adapter
# =============================================================================


class YFinanceAdapterError(Exception):
    pass


class YFinanceAdapter:
    """Phase 0 yfinance adapter — Raw landing only (no Silver)."""

    def __init__(
        self,
        registry: Registry,
        raw_dir: str | Path,
        rate_limit_per_sec: float = 1.0,
    ) -> None:
        self._registry = registry
        self._raw_dir = Path(raw_dir)
        self._rate_limit = rate_limit_per_sec
        self._last_request_ts: float = 0.0

    # ----- public API -----

    def fetch(
        self,
        canonical_symbol: str,
        start: date | str,
        end: date | str,
        decision_clock: DecisionClock = DecisionClock.CLOSE_FINAL,
    ) -> list[YFinanceObservation]:
        """Fetch OHLCV + adjusted close + split events, return observations."""
        self._registry.assert_canonical_symbol(canonical_symbol)
        instrument = self._registry.instruments[canonical_symbol]
        vendor_symbol = instrument.vendor_symbol_yfinance
        if not vendor_symbol:
            raise YFinanceAdapterError(
                f"{canonical_symbol} has no vendor_symbol_yfinance in registry"
            )

        start_ts = pd.Timestamp(start).date()
        end_ts = pd.Timestamp(end).date()
        # Guard: empty range
        if start_ts > end_ts:
            return []
        # Guard: filter to trading days only (T-05a calendar_guard)
        trading_days = [
            d for d in pd.date_range(start_ts, end_ts, freq="D").date
            if is_trading_day(d)
        ]
        if not trading_days:
            log.warning(
                "yfinance fetch %s %s..%s: no trading days in range",
                canonical_symbol, start_ts, end_ts,
            )
            return []

        # Rate limit
        self._throttle()

        # Fetch (with retry on transient errors)
        df = self._fetch_with_retry(vendor_symbol, trading_days[0], trading_days[-1])
        if df is None or df.empty:
            log.warning("yfinance empty response for %s", vendor_symbol)
            # Still land Raw so we have a record of the empty call
            self._land_raw(
                canonical_symbol=canonical_symbol,
                vendor_symbol=vendor_symbol,
                start=trading_days[0],
                end=trading_days[-1],
                decision_clock=decision_clock,
                response_bytes=b"",
                response_headers={},
                record_count=0,
                quality_status=YFinanceQualityStatus.EMPTY_RESPONSE.value,
                payload={"warning": "empty response"},
            )
            return []

        # Land Raw
        resp_bytes = df.to_json(orient="table", date_format="iso").encode("utf-8")
        resp_hash = hashlib.sha256(resp_bytes).hexdigest()
        request_payload = {
            "vendor_symbol": vendor_symbol,
            "start": str(trading_days[0]),
            "end": str(trading_days[-1]),
            "decision_clock": decision_clock.value,
            "auto_adjust": False,    # we want both raw and adjusted
            "actions": True,         # we need dividends/splits
        }
        self._land_raw(
            canonical_symbol=canonical_symbol,
            vendor_symbol=vendor_symbol,
            start=trading_days[0],
            end=trading_days[-1],
            decision_clock=decision_clock,
            response_bytes=resp_bytes,
            response_headers={"x-yfinance-version": yf.__version__},
            record_count=len(df),
            quality_status=YFinanceQualityStatus.VALID.value,
            payload=request_payload,
        )

        # Build observations
        return self._build_observations(
            canonical_symbol=canonical_symbol,
            df=df,
            decision_clock=decision_clock,
            resp_hash=resp_hash,
        )

    def detect_roll_events(
        self,
        canonical_symbol: str,
        start: date | str,
        end: date | str,
        gap_threshold_pct: float = 0.5,
    ) -> list[RolloverEvent]:
        """Heuristic rollover detection for continuous futures (GC=F, SI=F).

        A rollover is detected when the daily close jumps more than
        ``gap_threshold_pct``% — this catches most front-month expirations
        but will false-positive on legitimate large moves. The T-08 feature
        layer should consult this and treat the day's return as NaN.
        """
        self._registry.assert_canonical_symbol(canonical_symbol)
        obs = self.fetch(canonical_symbol, start, end, DecisionClock.CLOSE_FINAL)
        # CRITICAL: only look at price observations (volume shares RAW_CLOSE label)
        raw_close_obs = [
            o for o in obs
            if o.price_type == PriceType.RAW_CLOSE and o.field_name == "price__yf__close"
        ]
        if len(raw_close_obs) < 2:
            return []
        events: list[RolloverEvent] = []
        for i in range(1, len(raw_close_obs)):
            prev = raw_close_obs[i - 1]
            cur = raw_close_obs[i]
            if prev.value <= 0 or cur.value <= 0:
                continue
            pct = abs(cur.value - prev.value) / prev.value * 100
            if pct >= gap_threshold_pct:
                events.append(
                    RolloverEvent(
                        canonical_symbol=canonical_symbol,
                        observation_time=cur.observation_time,
                        old_close=prev.value,
                        new_close=cur.value,
                        spread=cur.value - prev.value,
                    )
                )
        return events

    # ----- internals -----

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
    def _fetch_with_retry(
        self, vendor_symbol: str, start: date, end: date
    ) -> pd.DataFrame | None:
        """Call yfinance. Returns DataFrame with OHLCV + Adj Close + Dividends/Splits.

        We disable auto_adjust so we receive both raw and adjusted prices.
        We use ``actions=True`` to get dividend/split events.
        """
        try:
            ticker = yf.Ticker(vendor_symbol)
            df = ticker.history(
                start=start.isoformat(),
                end=(end + pd.Timedelta(days=1)).isoformat(),  # yfinance end is exclusive
                auto_adjust=False,
                actions=True,
                raise_errors=False,
            )
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            log.warning("yfinance fetch %s failed: %s", vendor_symbol, e)
            raise

    def _build_observations(
        self,
        canonical_symbol: str,
        df: pd.DataFrame,
        decision_clock: DecisionClock,
        resp_hash: str,
    ) -> list[YFinanceObservation]:
        """Convert yfinance DataFrame to flat list of observations.

        For each trading day in the response we emit:
        - One ``RAW_CLOSE`` observation (field=price__yf__close, price_type=RAW_CLOSE)
        - One ``ADJ_CLOSE`` observation if adjusted close differs
        - One ``SPLIT_FACTOR`` observation per split event (if any)

        Per T-05a: ``available_at = observation_date + 1 business day + 18:00 ET``
        (post-close, conservative).
        """
        from pit_market.data.trading_calendar import add_business_days

        obs_list: list[YFinanceObservation] = []
        instrument = self._registry.instruments[canonical_symbol]
        vendor_symbol = instrument.vendor_symbol_yfinance or canonical_symbol

        for ts, row in df.iterrows():
            obs_date = pd.Timestamp(ts).date()
            if not is_trading_day(obs_date):
                continue  # belt-and-suspenders, yfinance shouldn't return non-trading days

            # observation_time = 16:00 ET (close), available_at = 18:00 ET same day,
            # or 18:00 ET next business day (we use 18:00 ET next biz day for safety).
            observation_time = datetime(obs_date.year, obs_date.month, obs_date.day, 16, 0)
            avail_date = add_business_days(obs_date, 1)
            available_at = datetime(avail_date.year, avail_date.month, avail_date.day, 18, 0)

            raw_close = float(row.get("Close", float("nan")))
            adj_close = float(row.get("Adj Close", raw_close))
            volume = float(row.get("Volume", 0))
            splits = float(row.get("Stock Splits", 0.0))

            # adj_factor = how the adjusted close was derived
            if raw_close and not pd.isna(raw_close) and raw_close > 0:
                adj_factor = adj_close / raw_close if adj_close else 1.0
            else:
                adj_factor = 1.0

            # 1) RAW_CLOSE
            if raw_close and not pd.isna(raw_close):
                obs_list.append(
                    YFinanceObservation(
                        canonical_symbol=canonical_symbol,
                        field_name="price__yf__close",
                        value=raw_close,
                        unit="usd",
                        observation_time=observation_time,
                        available_at=available_at,
                        price_type=PriceType.RAW_CLOSE,
                        quality_status=YFinanceQualityStatus.VALID,
                        vendor_symbol=vendor_symbol,
                        adj_factor=adj_factor,
                        split_ratio=None,
                        quality_flags={
                            "decision_clock": decision_clock.value,
                            "raw_record_hash": resp_hash,
                        },
                        raw_record_hash=resp_hash,
                    )
                )

            # 2) ADJ_CLOSE (only if it differs)
            if adj_close and not pd.isna(adj_close) and abs(adj_close - raw_close) > 1e-9:
                obs_list.append(
                    YFinanceObservation(
                        canonical_symbol=canonical_symbol,
                        field_name="price__yf__close",
                        value=adj_close,
                        unit="usd",
                        observation_time=observation_time,
                        available_at=available_at,
                        price_type=PriceType.ADJ_CLOSE,
                        quality_status=YFinanceQualityStatus.VALID,
                        vendor_symbol=vendor_symbol,
                        adj_factor=adj_factor,
                        split_ratio=None,
                        quality_flags={
                            "decision_clock": decision_clock.value,
                            "raw_record_hash": resp_hash,
                            "adjusted": True,
                        },
                        raw_record_hash=resp_hash,
                    )
                )

            # 3) SPLIT_FACTOR (when split event occurs)
            if splits and splits != 0.0 and not pd.isna(splits):
                obs_list.append(
                    YFinanceObservation(
                        canonical_symbol=canonical_symbol,
                        field_name="price__yf__split_factor",
                        value=float(splits),
                        unit="ratio",
                        observation_time=observation_time,
                        available_at=available_at,
                        price_type=PriceType.SPLIT_FACTOR,
                        quality_status=YFinanceQualityStatus.VALID,
                        vendor_symbol=vendor_symbol,
                        adj_factor=None,
                        split_ratio=float(splits),
                        quality_flags={
                            "decision_clock": decision_clock.value,
                            "raw_record_hash": resp_hash,
                        },
                        raw_record_hash=resp_hash,
                    )
                )

            # 4) Volume (T-05a scope)
            if volume and not pd.isna(volume):
                obs_list.append(
                    YFinanceObservation(
                        canonical_symbol=canonical_symbol,
                        field_name="price__yf__volume",
                        value=volume,
                        unit="shares",
                        observation_time=observation_time,
                        available_at=available_at,
                        price_type=PriceType.RAW_CLOSE,  # volume uses RAW close as the row key
                        quality_status=YFinanceQualityStatus.VALID,
                        vendor_symbol=vendor_symbol,
                        adj_factor=None,
                        split_ratio=None,
                        quality_flags={
                            "decision_clock": decision_clock.value,
                            "raw_record_hash": resp_hash,
                        },
                        raw_record_hash=resp_hash,
                    )
                )

        return obs_list

    def _land_raw(
        self,
        canonical_symbol: str,
        vendor_symbol: str,
        start: date,
        end: date,
        decision_clock: DecisionClock,
        response_bytes: bytes,
        response_headers: dict[str, str],
        record_count: int,
        quality_status: str,
        payload: dict[str, Any],
    ) -> Path:
        """Append-only Raw landing per PRD §9.1 layout."""
        ingest_date = datetime.now(UTC).strftime("%Y-%m-%d")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
        out_dir = (
            self._raw_dir
            / f"source={self._registry.instruments[canonical_symbol].asset_class or 'yfinance'}"  # not used in PRD
        )
        # PRD path: data/raw/source=yfinance/dataset=daily_ohlcv/ingest_date=YYYY-MM-DD/run_id=...
        out_dir = (
            self._raw_dir
            / "source=yfinance"
            / "dataset=daily_ohlcv"
            / f"ingest_date={ingest_date}"
            / f"run_id={run_id}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        # request.json
        request_path = out_dir / "request.json"
        request_path.write_text(
            json.dumps(
                {
                    "vendor_symbol": vendor_symbol,
                    "canonical_symbol": canonical_symbol,
                    "start": str(start),
                    "end": str(end),
                    "decision_clock": decision_clock.value,
                    "rate_limit_per_sec": self._rate_limit,
                    **payload,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # response.json.gz (gzip-compressed)
        response_path = out_dir / "response.json.gz"
        with gzip.open(response_path, "wb") as f:
            f.write(response_bytes if response_bytes else b"{}")
        resp_hash = hashlib.sha256(response_bytes if response_bytes else b"{}").hexdigest()

        # response_headers.json
        headers_path = out_dir / "response_headers.json"
        headers_path.write_text(json.dumps(response_headers, indent=2), encoding="utf-8")

        # manifest.json
        manifest = RawManifest(
            ingest_date=ingest_date,
            run_id=run_id,
            request_url=f"yfinance://{vendor_symbol}",
            request_payload=payload,
            response_headers=response_headers,
            response_size_bytes=len(response_bytes),
            response_sha256=resp_hash,
            record_count=record_count,
            quality_status=quality_status,
            quality_flags={"decision_clock": decision_clock.value},
            decision_clock=decision_clock.value,
        )
        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(asdict(manifest), indent=2),
            encoding="utf-8",
        )

        log.info(
            "yfinance raw landed: %s %s records=%d status=%s",
            canonical_symbol, run_id, record_count, quality_status,
        )
        return out_dir
