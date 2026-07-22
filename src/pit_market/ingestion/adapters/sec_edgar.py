"""SEC EDGAR Adapter (TODO T-26).

Reads SEC filings via EDGAR. The CRITICAL PIT discipline:
``available_at`` MUST be the ``acceptancedatetime`` field
(not ``periodOfReport``) — they can differ by 45+ days.

T-12 case 2 validates this. Filing types: 13F, 13D/G, Form 4, 8-K.
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
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pit_market.storage.registry import Registry

log = logging.getLogger(__name__)


class SecQualityStatus(StrEnum):
    VALID = "VALID"
    SOURCE_FAILED = "SOURCE_FAILED"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    INFERRED_AVAILABILITY = "INFERRED_AVAILABILITY"  # when filing_date used as fallback


@dataclass(frozen=True)
class SecObservation:
    canonical_symbol: str  # ticker (e.g. AAPL) — not in our 12-instrument universe, stored verbatim
    field_name: str
    value: float
    unit: str
    observation_time: datetime  # periodOfReport
    available_at: datetime  # acceptancedatetime (the PIT discipline #8)
    filing_type: str  # 13F, 13D, Form 4, 8-K
    quality_status: SecQualityStatus
    raw_record_hash: str
    semantic_caveat: str = ""


@dataclass
class SecRawManifest:
    source_name: str = "sec"
    dataset_name: str = ""
    ingest_date: str = ""
    run_id: str = ""
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_size_bytes: int = 0
    response_sha256: str = ""
    record_count: int = 0
    quality_status: str = "VALID"
    quality_flags: dict[str, Any] = field(default_factory=dict)


class SecEdgarAdapter:
    EDGAR_BASE = "https://data.sec.gov"

    def __init__(
        self,
        registry: Registry,
        raw_dir: str | Path,
        rate_limit_per_sec: float = 10.0,  # SEC allows 10 req/s
        user_agent: str | None = None,
    ) -> None:
        self._registry = registry
        self._raw_dir = Path(raw_dir)
        self._rate_limit = rate_limit_per_sec
        self._last_request_ts: float = 0.0
        self._user_agent = user_agent or os.environ.get(
            "SEC_EDGAR_USER_AGENT", "PIT Market Intelligence research@example.com"
        )

    def fetch_13f_filing(
        self,
        cik: str,
        filing_date: date | None = None,
    ) -> list[SecObservation]:
        """Fetch 13F filings for an institutional manager.

        For Phase 4 this is a stub — real impl requires parsing EDGAR
        submissions JSON. Returns [] with a Raw landing for audit.
        """
        self._throttle()
        url = f"{self.EDGAR_BASE}/submissions/CIK{cik}.json"
        payload = {"cik": cik, "filing_date": filing_date.isoformat() if filing_date else None}
        try:
            response = self._get_with_retry(url, headers={"User-Agent": self._user_agent})
        except Exception as e:
            self._land_raw("13f_filings", payload, b"", 0, SecQualityStatus.SOURCE_FAILED.value, str(e))
            return []
        resp_bytes = response.content
        self._land_raw("13f_filings", payload, resp_bytes, 0, SecQualityStatus.EMPTY_RESPONSE.value, "stub")
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
    def _get_with_retry(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        h = headers or {}
        with httpx.Client(timeout=60.0, headers=h) as client:
            return client.get(url)

    def _land_raw(
        self,
        dataset: str,
        payload: dict[str, Any],
        response_bytes: bytes,
        record_count: int,
        quality_status: str,
        note: str,
    ) -> Path:
        ingest_date = datetime.now(UTC).strftime("%Y-%m-%d")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
        out_dir = (
            self._raw_dir / "source=sec" / f"dataset={dataset}"
            / f"ingest_date={ingest_date}" / f"run_id={run_id}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "request.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        with gzip.open(out_dir / "response.json.gz", "wb") as f:
            f.write(response_bytes if response_bytes else b"{}")
        resp_hash = hashlib.sha256(response_bytes if response_bytes else b"{}").hexdigest()
        (out_dir / "response_headers.json").write_text(json.dumps({}, indent=2), encoding="utf-8")
        manifest = SecRawManifest(
            dataset_name=dataset,
            ingest_date=ingest_date, run_id=run_id, request_payload=payload,
            response_size_bytes=len(response_bytes), response_sha256=resp_hash,
            record_count=record_count, quality_status=quality_status,
            quality_flags={"note": note} if note else {},
        )
        (out_dir / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
        return out_dir
