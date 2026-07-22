"""Cboe CFE (VIX futures) Adapter (TODO T-26).

VIX futures daily volume / OI. Per PRD: real-time market data, NOT
through FRED (FRED lags 1-2 days). Use ``decision_clock=1605_ET``
for real-time or `close_final=1805_ET` for end-of-day.
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

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pit_market.storage.registry import Registry

log = logging.getLogger(__name__)


class CfeQualityStatus(StrEnum):
    VALID = "VALID"
    SOURCE_FAILED = "SOURCE_FAILED"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"


@dataclass(frozen=True)
class CfeObservation:
    canonical_symbol: str
    field_name: str
    value: float
    unit: str
    observation_time: datetime
    available_at: datetime
    contract_code: str  # e.g. VX (VIX front month), UX (VIX2)
    quality_status: CfeQualityStatus
    raw_record_hash: str


@dataclass
class CfeRawManifest:
    source_name: str = "cboe_cfe"
    dataset_name: str = "vix_futures_daily"
    ingest_date: str = ""
    run_id: str = ""
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_size_bytes: int = 0
    response_sha256: str = ""
    record_count: int = 0
    quality_status: str = "VALID"
    quality_flags: dict[str, Any] = field(default_factory=dict)


class CboeCfeAdapter:
    Cboe_BASE = "https://www.cboe.com"

    def __init__(self, registry: Registry, raw_dir: str | Path, rate_limit_per_sec: float = 1.0) -> None:
        self._registry = registry
        self._raw_dir = Path(raw_dir)
        self._rate_limit = rate_limit_per_sec
        self._last_request_ts: float = 0.0

    def fetch_day(self, observation_date: date) -> list[CfeObservation]:
        """Fetch daily VIX futures volume for ``observation_date``.

        VIX front-month (VX) is the most-watched. We use the registered
        ``VIX`` canonical_symbol as a proxy in the registry.
        """
        self._throttle()
        # CFE publishes at end-of-day (16:00 ET settlement), available 18:00 ET
        url = (
            f"{self.Cboe_BASE}/us/futures/market_statistics/daily/"
            f"?dt={observation_date.isoformat()}"
        )
        payload = {"date": observation_date.isoformat()}
        try:
            response = self._get_with_retry(url)
        except Exception as e:
            self._land_raw(payload, b"", 0, CfeQualityStatus.SOURCE_FAILED.value, str(e))
            return []
        resp_bytes = response.content
        # Real impl parses HTML/CSV; for Phase 4 we return an empty list
        # unless the response actually has data. Mark as VALID landing only.
        self._land_raw(payload, resp_bytes, 0, CfeQualityStatus.EMPTY_RESPONSE.value, "stub: real CFE parser ships in T-26 follow-up")
        return []

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < 1.0 / self._rate_limit:
            time.sleep(1.0 / self._rate_limit - elapsed)
        self._last_request_ts = time.monotonic()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _get_with_retry(self, url: str) -> httpx.Response:
        with httpx.Client(timeout=60.0) as client:
            return client.get(url)

    def _land_raw(self, payload, response_bytes, record_count, quality_status, note) -> Path:
        ingest_date = datetime.now(UTC).strftime("%Y-%m-%d")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
        out_dir = self._raw_dir / "source=cboe_cfe" / "dataset=vix_futures_daily" / f"ingest_date={ingest_date}" / f"run_id={run_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "request.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        with gzip.open(out_dir / "response.json.gz", "wb") as f:
            f.write(response_bytes if response_bytes else b"{}")
        resp_hash = hashlib.sha256(response_bytes if response_bytes else b"{}").hexdigest()
        (out_dir / "response_headers.json").write_text(json.dumps({}, indent=2), encoding="utf-8")
        manifest = CfeRawManifest(
            ingest_date=ingest_date, run_id=run_id, request_payload=payload,
            response_size_bytes=len(response_bytes), response_sha256=resp_hash,
            record_count=record_count, quality_status=quality_status,
            quality_flags={"note": note} if note else {},
        )
        (out_dir / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
        return out_dir
