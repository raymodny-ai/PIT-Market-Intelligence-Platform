"""FRED / ALFRED Adapter (TODO T-05b).

CRITICAL discipline (PIT #8):
- This adapter MUST call the ALFRED API, NOT the FRED main API.
  Calling FRED directly returns latest-revised values, which silently
  introduces forward-look bias in any historical PIT replay.
- Every request MUST include ``realtime_start`` (set to ``ingest_date``).
- Raw ``request.json`` MUST persist the realtime parameters for replay
  and audit.

Reference: https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pit_market.data.trading_calendar import add_business_days
from pit_market.storage.registry import Registry

log = logging.getLogger(__name__)


# =============================================================================
# Domain types
# =============================================================================


class FredQualityStatus(StrEnum):
    VALID = "VALID"
    SOURCE_THROTTLED = "SOURCE_THROTTLED"
    SOURCE_FAILED = "SOURCE_FAILED"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    MISSING_API_KEY = "MISSING_API_KEY"


@dataclass(frozen=True)
class FredObservation:
    canonical_symbol: str
    field_name: str
    value: float
    unit: str
    observation_time: datetime
    available_at: datetime
    vendor_series_id: str
    vintage_date: datetime
    quality_status: FredQualityStatus
    raw_record_hash: str
    semantic_caveat: str = ""


@dataclass
class FredRawManifest:
    source_name: str = "fred"
    dataset_name: str = ""
    ingest_date: str = ""
    run_id: str = ""
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_size_bytes: int = 0
    response_sha256: str = ""
    record_count: int = 0
    quality_status: str = "VALID"
    quality_flags: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Adapter
# =============================================================================


class FredAdapterError(Exception):
    pass


class FredAlfredAdapter:
    """Phase 1 FRED/ALFRED adapter — ALFRED-only, vintage-aware."""

    ALFRED_BASE = "https://api.stlouisfed.org"

    def __init__(
        self,
        registry: Registry,
        raw_dir: str | Path,
        api_key: str | None = None,
        rate_limit_per_sec: float = 1.0,
    ) -> None:
        self._registry = registry
        self._raw_dir = Path(raw_dir)
        self._api_key = api_key or os.environ.get("FRED_API_KEY")
        self._rate_limit = rate_limit_per_sec
        self._last_request_ts: float = 0.0
        if not self._api_key:
            log.warning(
                "FRED_API_KEY not set — adapter will fail on real calls. "
                "Set FRED_API_KEY in .env for production use."
            )

    # ----- public -----

    def fetch_series(
        self,
        series_id: str,
        start: date | str,
        end: date | str,
        realtime_start: date | str | None = None,
        realtime_end: date | str | None = None,
    ) -> list[FredObservation]:
        """Fetch a FRED series via ALFRED. Returns list of FredObservation.

        Args:
            series_id: e.g. "DGS10", "VIXCLS", "T10YIE"
            start: observation start (inclusive)
            end: observation end (inclusive)
            realtime_start: historical vintage point. Defaults to ``start``.
                MUST be set for PIT discipline (otherwise latest-revised values).
            realtime_end: end of vintage window. Defaults to ``realtime_start``
                (point-in-time query).
        """
        if not self._api_key:
            raise FredAdapterError(
                "FRED_API_KEY not configured — set env var or pass api_key="
            )

        # Discipline #8: realtime_start MUST be set
        rt_start = realtime_start or start
        rt_end = realtime_end or rt_start

        self._throttle()

        # ALFRED URL: observations endpoint with realtime_* parameters
        url = f"{self.ALFRED_BASE}/fred/series/observations"
        params = {
            "api_key": self._api_key,
            "series_id": series_id,
            "file_type": "json",
            "observation_start": str(start),
            "observation_end": str(end),
            "realtime_start": str(rt_start),
            "realtime_end": str(rt_end),
            "sort_order": "asc",
        }
        dict(params)
        # Strip api_key from logged payload (security)
        request_payload_logged = {k: v for k, v in params.items() if k != "api_key"}

        try:
            response = self._get_with_retry(url, params)
        except Exception as e:
            self._land_raw(
                series_id=series_id,
                request_payload=request_payload_logged,
                response_bytes=b"",
                record_count=0,
                quality_status=FredQualityStatus.SOURCE_FAILED.value,
                note=str(e),
            )
            log.error("FRED fetch %s failed: %s", series_id, e)
            return []

        resp_bytes = response.content
        resp_hash = hashlib.sha256(resp_bytes).hexdigest()

        try:
            resp_json = response.json()
        except json.JSONDecodeError as e:
            self._land_raw(
                series_id=series_id,
                request_payload=request_payload_logged,
                response_bytes=resp_bytes,
                record_count=0,
                quality_status=FredQualityStatus.SOURCE_FAILED.value,
                note=f"JSON decode error: {e}",
            )
            return []

        observations_raw = resp_json.get("observations", [])
        if not observations_raw:
            self._land_raw(
                series_id=series_id,
                request_payload=request_payload_logged,
                response_bytes=resp_bytes,
                record_count=0,
                quality_status=FredQualityStatus.EMPTY_RESPONSE.value,
                note="ALFRED returned 0 observations",
            )
            return []

        # Land Raw (valid response)
        self._land_raw(
            series_id=series_id,
            request_payload=request_payload_logged,
            response_bytes=resp_bytes,
            record_count=len(observations_raw),
            quality_status=FredQualityStatus.VALID.value,
            note="",
        )

        return self._build_observations(
            series_id=series_id,
            observations_raw=observations_raw,
            realtime_start=pd.Timestamp(rt_start).date(),
            resp_hash=resp_hash,
        )

    # ----- helpers -----

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        min_interval = 1.0 / self._rate_limit
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_ts = time.monotonic()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _get_with_retry(self, url: str, params: dict[str, str]) -> httpx.Response:
        with httpx.Client(timeout=30.0) as client:
            return client.get(url, params=params)

    def _build_observations(
        self,
        series_id: str,
        observations_raw: list[dict],
        realtime_start: date,
        resp_hash: str,
    ) -> list[FredObservation]:
        out: list[FredObservation] = []
        rt_start_ts = pd.Timestamp(realtime_start)
        # ALFRED vintage_date defaults to realtime_start when not specified
        for obs in observations_raw:
            obs_date_str = obs.get("date", "")
            if not obs_date_str:
                continue
            try:
                obs_date = datetime.strptime(obs_date_str, "%Y-%m-%d")
            except ValueError:
                continue

            value_str = obs.get("value", ".")
            if value_str in (".", "", None):
                continue  # ALFRED encodes missing as "."
            try:
                value = float(value_str)
            except ValueError:
                continue

            # observation_time = 00:00 UTC of obs date (FRED convention)
            observation_time = datetime(obs_date.year, obs_date.month, obs_date.day, 0, 0)
            # available_at = realtime_start (vintage date) + 1 business day @ 18:00 ET
            avail_date = add_business_days(realtime_start, 1)
            available_at = datetime(avail_date.year, avail_date.month, avail_date.day, 18, 0)

            # Find matching metric for semantic_warning
            metric = self._find_metric(series_id)
            caveat = metric.semantic_warning if metric else ""

            out.append(
                FredObservation(
                    canonical_symbol="MACRO",  # macro fields are not per-symbol; we use a placeholder
                    field_name=metric.field_name if metric else f"macro__fred__{series_id.lower()}",
                    value=value,
                    unit=metric.unit if metric else "",
                    observation_time=observation_time,
                    available_at=available_at,
                    vendor_series_id=series_id,
                    vintage_date=datetime(
                        rt_start_ts.year, rt_start_ts.month, rt_start_ts.day
                    ),
                    quality_status=FredQualityStatus.VALID,
                    raw_record_hash=resp_hash,
                    semantic_caveat=caveat,
                )
            )
        return out

    def _find_metric(self, series_id: str):
        """Find a metric in registry by FRED dataset_name == series_id."""
        for _fn, m in self._registry.metrics.items():
            if m.source_name == "fred" and m.dataset_name == series_id:
                return m
        return None

    def _land_raw(
        self,
        series_id: str,
        request_payload: dict[str, Any],
        response_bytes: bytes,
        record_count: int,
        quality_status: str,
        note: str,
    ) -> Path:
        ingest_date = datetime.now(UTC).strftime("%Y-%m-%d")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
        out_dir = (
            self._raw_dir
            / "source=fred"
            / f"dataset={series_id}"
            / f"ingest_date={ingest_date}"
            / f"run_id={run_id}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        # request.json (api_key MUST NOT be in here; we strip in caller)
        request_path = out_dir / "request.json"
        request_path.write_text(
            json.dumps(request_payload, indent=2), encoding="utf-8"
        )

        # response.json.gz
        response_path = out_dir / "response.json.gz"
        with gzip.open(response_path, "wb") as f:
            f.write(response_bytes if response_bytes else b"{}")
        resp_hash = hashlib.sha256(response_bytes if response_bytes else b"{}").hexdigest()

        # response_headers.json
        headers_path = out_dir / "response_headers.json"
        headers_path.write_text(json.dumps({}, indent=2), encoding="utf-8")

        # manifest.json
        manifest = FredRawManifest(
            dataset_name=series_id,
            ingest_date=ingest_date,
            run_id=run_id,
            request_payload=request_payload,
            response_size_bytes=len(response_bytes),
            response_sha256=resp_hash,
            record_count=record_count,
            quality_status=quality_status,
            quality_flags={"note": note} if note else {},
        )
        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(asdict(manifest), indent=2), encoding="utf-8"
        )

        log.info(
            "FRED/ALFRED raw landed: %s records=%d status=%s",
            series_id, record_count, quality_status,
        )
        return out_dir
