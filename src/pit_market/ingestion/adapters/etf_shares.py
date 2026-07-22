"""ETF Issuer Shares Outstanding Adapter (TODO T-26).

Per PRD: shares_outstanding is the proxy for ETF fund flow. The
available_at depends on the issuer:

- State Street (GLD, SLV): T+1 10:00 ET (22h offset)
- BlackRock (IAU, IWM): T-day 20:00 ET (4h offset)
- Invesco (QQQ): T-day ~18:00 ET (18h offset)

Critical PIT discipline (T-12 case 14): using the wrong issuer's
rule means the data appears too early (forward-look bias).

We route by ``Instrument.issuer`` field in registry.
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

from pit_market.storage.registry import Registry

log = logging.getLogger(__name__)


# Issuer release schedule (hours after T-day close)
ISSUER_RELEASE_HOURS = {
    "state_street": 22,  # T+1 10:00 ET
    "blackrock": 4,      # T-day 20:00 ET
    "invesco": 18,       # T-day 18:00 ET
    "vanguard": 18,
}


class EtfQualityStatus(StrEnum):
    VALID = "VALID"
    SOURCE_FAILED = "SOURCE_FAILED"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"


@dataclass(frozen=True)
class EtfObservation:
    canonical_symbol: str
    field_name: str
    value: float
    unit: str
    observation_time: datetime
    available_at: datetime
    issuer: str
    quality_status: EtfQualityStatus
    raw_record_hash: str
    semantic_caveat: str = ""


@dataclass
class EtfRawManifest:
    source_name: str = "etf_issuer"
    dataset_name: str = ""
    ingest_date: str = ""
    run_id: str = ""
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_size_bytes: int = 0
    response_sha256: str = ""
    record_count: int = 0
    quality_status: str = "VALID"
    quality_flags: dict[str, Any] = field(default_factory=dict)


class EtfSharesAdapter:
    """Issuer-routed ETF shares outstanding adapter."""

    def __init__(self, registry: Registry, raw_dir: str | Path, rate_limit_per_sec: float = 0.5) -> None:
        self._registry = registry
        self._raw_dir = Path(raw_dir)
        self._rate_limit = rate_limit_per_sec
        self._last_request_ts: float = 0.0

    def resolve_availability(self, canonical_symbol: str, observation_date: date) -> datetime:
        """Compute ``available_at`` based on the issuer's release schedule."""
        inst = self._registry.instruments.get(canonical_symbol)
        if inst is None:
            raise ValueError(f"Unknown symbol: {canonical_symbol}")
        issuer = inst.issuer or "default"
        hours = ISSUER_RELEASE_HOURS.get(issuer, 18)  # default 18h
        # T-day close is 16:00 ET; +N hours
        avail = datetime(observation_date.year, observation_date.month, observation_date.day, 16, 0) + \
                _timedelta(hours=hours)
        return avail

    def fetch_shares(self, canonical_symbol: str, observation_date: date) -> list[EtfObservation]:
        """Fetch ETF shares outstanding for a single day.

        For Phase 4 this is a stub — real impl scrapes the issuer's
        website. Returns [] with Raw landing for audit + the resolved
        available_at computed from the issuer's release schedule.
        """
        self._throttle()
        try:
            self.resolve_availability(canonical_symbol, observation_date)
        except ValueError:
            return []

        inst = self._registry.instruments[canonical_symbol]
        payload = {
            "canonical_symbol": canonical_symbol,
            "observation_date": observation_date.isoformat(),
            "issuer": inst.issuer,
        }
        self._land_raw(canonical_symbol, payload, b"", 0, EtfQualityStatus.EMPTY_RESPONSE.value, "stub")
        return []

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < 1.0 / self._rate_limit:
            time.sleep(1.0 / self._rate_limit - elapsed)
        self._last_request_ts = time.monotonic()

    def _land_raw(self, symbol: str, payload, response_bytes, record_count, quality_status, note) -> Path:
        ingest_date = datetime.now(UTC).strftime("%Y-%m-%d")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
        out_dir = (
            self._raw_dir / "source=etf_issuer" / f"dataset={symbol}_shares"
            / f"ingest_date={ingest_date}" / f"run_id={run_id}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "request.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        with gzip.open(out_dir / "response.json.gz", "wb") as f:
            f.write(response_bytes if response_bytes else b"{}")
        resp_hash = hashlib.sha256(response_bytes if response_bytes else b"{}").hexdigest()
        (out_dir / "response_headers.json").write_text(json.dumps({}, indent=2), encoding="utf-8")
        manifest = EtfRawManifest(
            dataset_name=f"{symbol}_shares",
            ingest_date=ingest_date, run_id=run_id, request_payload=payload,
            response_size_bytes=len(response_bytes), response_sha256=resp_hash,
            record_count=record_count, quality_status=quality_status,
            quality_flags={"note": note} if note else {},
        )
        (out_dir / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
        return out_dir


def _timedelta(hours: int):  # small helper to avoid importing timedelta at module level
    from datetime import timedelta
    return timedelta(hours=hours)
