"""FINRA OTC Transparency Adapter (TODO T-26).

ATS / non-ATS volume per venue, published weekly (PRD §3).
Semantic warning: ATS volume != real money flow.
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

from pit_market.data.trading_calendar import add_business_days
from pit_market.storage.registry import Registry

log = logging.getLogger(__name__)


class OtcQualityStatus(StrEnum):
    VALID = "VALID"
    SOURCE_FAILED = "SOURCE_FAILED"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"


@dataclass(frozen=True)
class OtcObservation:
    canonical_symbol: str
    field_name: str
    value: float
    unit: str
    observation_time: datetime
    available_at: datetime  # obs_date + 2 biz (T+2 — OTC lags behind)
    venue: str  # ATS or non-ATS
    quality_status: OtcQualityStatus
    raw_record_hash: str
    semantic_caveat: str = ""


@dataclass
class OtcRawManifest:
    source_name: str = "finra_otc"
    dataset_name: str = "weekly_otc"
    ingest_date: str = ""
    run_id: str = ""
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_size_bytes: int = 0
    response_sha256: str = ""
    record_count: int = 0
    quality_status: str = "VALID"
    quality_flags: dict[str, Any] = field(default_factory=dict)


class FinraOtcAdapter:
    FINRA_BASE = "https://api.finra.org"

    def __init__(self, registry: Registry, raw_dir: str | Path, rate_limit_per_sec: float = 0.5) -> None:
        self._registry = registry
        self._raw_dir = Path(raw_dir)
        self._rate_limit = rate_limit_per_sec
        self._last_request_ts: float = 0.0

    def fetch_week(self, week_ending: date) -> list[OtcObservation]:
        self._throttle()
        # FINRA OTC weekly; published ~2 business days after week-end
        avail_date = add_business_days(week_ending, 2)
        available_at = datetime(avail_date.year, avail_date.month, avail_date.day, 16, 0)
        observation_time = datetime(week_ending.year, week_ending.month, week_ending.day, 16, 0)

        url = (
            f"{self.FINRA_BASE}/data/group/otcmarket/name/otcSummaryWeekly"
            f"?limit=10000&filter=weekEndDate::eq::{week_ending.isoformat()}"
        )
        payload = {"week_ending": week_ending.isoformat()}
        try:
            response = self._get_with_retry(url)
        except Exception as e:
            self._land_raw(payload, b"", 0, OtcQualityStatus.SOURCE_FAILED.value, str(e))
            return []
        resp_bytes = response.content
        resp_hash = hashlib.sha256(resp_bytes).hexdigest()
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            self._land_raw(payload, resp_bytes, 0, OtcQualityStatus.SOURCE_FAILED.value, str(e))
            return []
        records = data if isinstance(data, list) else data.get("data", [])
        if not records:
            self._land_raw(payload, resp_bytes, 0, OtcQualityStatus.EMPTY_RESPONSE.value, "empty")
            return []
        self._land_raw(payload, resp_bytes, len(records), OtcQualityStatus.VALID.value, "")

        out: list[OtcObservation] = []
        for rec in records:
            symbol = rec.get("issueSymbolIdentifier") or rec.get("symbol")
            if not symbol:
                continue
            sym = self._find_canonical(symbol)
            if not sym:
                continue
            venue = rec.get("venue", "ATS")
            for field_suffix, json_key, unit in [
                ("total_volume", "totalWeeklyVolume", "shares"),
                ("total_trades", "totalWeeklyTradeCount", "trades"),
                ("total_dollars", "totalWeeklyDollars", "usd"),
            ]:
                v = self._to_float(rec.get(json_key))
                if v is None:
                    continue
                out.append(
                    OtcObservation(
                        canonical_symbol=sym,
                        field_name=f"otc__finra__{field_suffix}__{venue.lower()}",
                        value=v,
                        unit=unit,
                        observation_time=observation_time,
                        available_at=available_at,
                        venue=venue,
                        quality_status=OtcQualityStatus.VALID,
                        raw_record_hash=resp_hash,
                        semantic_caveat="ATS 数据 ≠ 实时资金流,反映的是 ATS 撮合成交量",
                    )
                )
        return out

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

    def _find_canonical(self, vendor_symbol: str) -> str | None:
        for sym, inst in self._registry.instruments.items():
            if inst.vendor_symbol_yfinance == vendor_symbol or sym == vendor_symbol:
                return sym
        return None

    def _to_float(self, v: Any) -> float | None:
        if v is None:
            return None
        try:
            return float(str(v).replace(",", ""))
        except (ValueError, TypeError):
            return None

    def _land_raw(self, payload, response_bytes, record_count, quality_status, note) -> Path:
        ingest_date = datetime.now(UTC).strftime("%Y-%m-%d")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
        out_dir = self._raw_dir / "source=finra_otc" / "dataset=weekly_otc" / f"ingest_date={ingest_date}" / f"run_id={run_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "request.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        with gzip.open(out_dir / "response.json.gz", "wb") as f:
            f.write(response_bytes if response_bytes else b"{}")
        resp_hash = hashlib.sha256(response_bytes if response_bytes else b"{}").hexdigest()
        (out_dir / "response_headers.json").write_text(json.dumps({}, indent=2), encoding="utf-8")
        manifest = OtcRawManifest(
            ingest_date=ingest_date, run_id=run_id, request_payload=payload,
            response_size_bytes=len(response_bytes), response_sha256=resp_hash,
            record_count=record_count, quality_status=quality_status,
            quality_flags={"note": note} if note else {},
        )
        (out_dir / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
        return out_dir
