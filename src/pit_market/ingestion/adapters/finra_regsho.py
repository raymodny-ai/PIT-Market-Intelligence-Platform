"""FINRA Reg SHO Adapter (TODO T-05d).

PIT discipline (T-05d / R-7):
- ``available_at`` = observation_date + 1 business day + 14:00 ET
  (conservative; some symbols publish on T+2 due to NYSE Arca latency)
- ``max_staleness = 2D`` (allows weekend carry-over)
- ``flow__finra__short_ratio`` must carry semantic_warning:
  "分母为 FINRA reporting venue 成交量,非全市场 consolidated volume"
- All short_ratio-derived features must keep numerator/denominator
  same-source (multi-source denominator discipline #8)

Source: FINRA publishes daily at https://api.finra.org/data/group/otcmarket/name/regsho
(publicly accessible; rate-limited).
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


# =============================================================================
# Domain types
# =============================================================================


class FinraQualityStatus(StrEnum):
    VALID = "VALID"
    SOURCE_THROTTLED = "SOURCE_THROTTLED"
    SOURCE_FAILED = "SOURCE_FAILED"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"


@dataclass(frozen=True)
class FinraObservation:
    canonical_symbol: str
    field_name: str
    value: float
    unit: str
    observation_time: datetime
    available_at: datetime  # obs_date + 1 biz + 14:00 ET
    vendor_symbol: str
    quality_status: FinraQualityStatus
    raw_record_hash: str
    semantic_caveat: str = ""


@dataclass
class FinraRawManifest:
    source_name: str = "finra"
    dataset_name: str = "regsho_daily"
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


class FinraAdapterError(Exception):
    pass


class FinraRegShoAdapter:
    """Phase 1 FINRA Reg SHO adapter — T+1 14:00 ET availability."""

    FINRA_BASE = "https://api.finra.org"

    def __init__(
        self,
        registry: Registry,
        raw_dir: str | Path,
        rate_limit_per_sec: float = 0.5,
    ) -> None:
        self._registry = registry
        self._raw_dir = Path(raw_dir)
        self._rate_limit = rate_limit_per_sec
        self._last_request_ts: float = 0.0

    # ----- public -----

    def fetch_day(self, observation_date: date) -> list[FinraObservation]:
        """Fetch Reg SHO data for a single trading day.

        T-12 case 11: Panel at obs_date 18:05 ET MUST NOT include this data
        (available_at = obs_date + 1 biz + 14:00 ET).
        """
        self._throttle()
        url = (
            f"{self.FINRA_BASE}/data/group/otcmarket/name/regsho"
            f"?limit=10000&filter=settlementDate::eq::{observation_date.isoformat()}"
        )
        payload = {"observation_date": observation_date.isoformat()}

        try:
            response = self._get_with_retry(url)
        except Exception as e:
            self._land_raw(
                request_payload=payload,
                response_bytes=b"",
                record_count=0,
                quality_status=FinraQualityStatus.SOURCE_FAILED.value,
                note=str(e),
            )
            log.error("FINRA fetch %s failed: %s", observation_date, e)
            return []

        resp_bytes = response.content
        resp_hash = hashlib.sha256(resp_bytes).hexdigest()
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            self._land_raw(
                request_payload=payload,
                response_bytes=resp_bytes,
                record_count=0,
                quality_status=FinraQualityStatus.SOURCE_FAILED.value,
                note=f"JSON: {e}",
            )
            return []

        records = data if isinstance(data, list) else data.get("data", [])
        if not records:
            self._land_raw(
                request_payload=payload,
                response_bytes=resp_bytes,
                record_count=0,
                quality_status=FinraQualityStatus.EMPTY_RESPONSE.value,
                note="empty",
            )
            return []

        self._land_raw(
            request_payload=payload,
            response_bytes=resp_bytes,
            record_count=len(records),
            quality_status=FinraQualityStatus.VALID.value,
            note="",
        )

        return self._build_observations(
            records=records,
            observation_date=observation_date,
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
    def _get_with_retry(self, url: str) -> httpx.Response:
        with httpx.Client(timeout=60.0) as client:
            return client.get(url)

    def _build_observations(
        self,
        records: list[dict],
        observation_date: date,
        resp_hash: str,
    ) -> list[FinraObservation]:
        """Build observations from FINRA records.

        For each symbol we emit:
        - short_volume
        - total_volume
        - short_ratio = short_volume / total_volume (if both > 0)

        ``available_at`` per T-05d: obs_date + 1 biz day + 14:00 ET
        """
        # PIT: available_at for obs_date D
        avail_date = add_business_days(observation_date, 1)
        available_at = datetime(avail_date.year, avail_date.month, avail_date.day, 14, 0)
        observation_time = datetime(
            observation_date.year, observation_date.month, observation_date.day, 16, 0
        )

        out: list[FinraObservation] = []
        for rec in records:
            vendor_sym = rec.get("symbolCode") or rec.get("symbol") or rec.get("Symbol")
            if not vendor_sym:
                continue
            sym = self._find_canonical(vendor_sym)
            if sym is None:
                # symbol not in our universe — skip silently
                continue
            short_vol = self._to_float(rec.get("shortVolume") or rec.get("shortvolume"))
            self._to_float(rec.get("shortExemptVolume") or rec.get("shortexemptvolume"))
            total_vol = self._to_float(rec.get("totalVolume") or rec.get("totalvolume"))

            # short_volume
            if short_vol is not None and short_vol > 0:
                out.append(
                    FinraObservation(
                        canonical_symbol=sym,
                        field_name="flow__finra__short_volume",
                        value=short_vol,
                        unit="shares",
                        observation_time=observation_time,
                        available_at=available_at,
                        vendor_symbol=vendor_sym,
                        quality_status=FinraQualityStatus.VALID,
                        raw_record_hash=resp_hash,
                        semantic_caveat=(
                            "short_volume 是 FINRA reporting venue 短卖成交量,"
                            "不等同于 short interest 或净空头仓位"
                        ),
                    )
                )

            # total_volume
            if total_vol is not None and total_vol > 0:
                out.append(
                    FinraObservation(
                        canonical_symbol=sym,
                        field_name="flow__finra__total_volume",
                        value=total_vol,
                        unit="shares",
                        observation_time=observation_time,
                        available_at=available_at,
                        vendor_symbol=vendor_sym,
                        quality_status=FinraQualityStatus.VALID,
                        raw_record_hash=resp_hash,
                        semantic_caveat=(
                            "总成交量为 FINRA reporting venue 成交量,非全市场"
                            " consolidated volume,不得直接与 SIP tape 成交占比对比"
                        ),
                    )
                )

            # short_ratio (multi-source denominator discipline #8: same source)
            if short_vol is not None and total_vol is not None and total_vol > 0 and short_vol > 0:
                ratio = short_vol / total_vol
                out.append(
                    FinraObservation(
                        canonical_symbol=sym,
                        field_name="flow__finra__short_ratio",
                        value=ratio,
                        unit="ratio",
                        observation_time=observation_time,
                        available_at=available_at,
                        vendor_symbol=vendor_sym,
                        quality_status=FinraQualityStatus.VALID,
                        raw_record_hash=resp_hash,
                        semantic_caveat=(
                            "分母为 FINRA reporting venue 成交量,非全市场 consolidated volume;"
                            "分子分母必须同源,不得混入其他数据源"
                        ),
                    )
                )

        return out

    def _to_float(self, v: Any) -> float | None:
        if v is None:
            return None
        try:
            return float(str(v).replace(",", ""))
        except (ValueError, TypeError):
            return None

    def _find_canonical(self, vendor_symbol: str) -> str | None:
        for sym, inst in self._registry.instruments.items():
            if inst.vendor_symbol_yfinance == vendor_symbol or sym == vendor_symbol:
                return sym
        return None

    def _land_raw(
        self,
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
            / "source=finra"
            / "dataset=regsho_daily"
            / f"ingest_date={ingest_date}"
            / f"run_id={run_id}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        (out_dir / "request.json").write_text(
            json.dumps(request_payload, indent=2), encoding="utf-8"
        )
        with gzip.open(out_dir / "response.json.gz", "wb") as f:
            f.write(response_bytes if response_bytes else b"{}")
        resp_hash = hashlib.sha256(response_bytes if response_bytes else b"{}").hexdigest()
        (out_dir / "response_headers.json").write_text(json.dumps({}, indent=2), encoding="utf-8")
        manifest = FinraRawManifest(
            ingest_date=ingest_date,
            run_id=run_id,
            request_payload=request_payload,
            response_size_bytes=len(response_bytes),
            response_sha256=resp_hash,
            record_count=record_count,
            quality_status=quality_status,
            quality_flags={"note": note} if note else {},
        )
        (out_dir / "manifest.json").write_text(
            json.dumps(asdict(manifest), indent=2), encoding="utf-8"
        )
        return out_dir
