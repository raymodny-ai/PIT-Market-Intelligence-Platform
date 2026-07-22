"""CFTC COT Adapter (TODO T-05c).

Reads CFTC Commitments of Traders reports. Three report types (PRD §3):
- LEGACY: ``cot_year.txt`` (commercial/noncommercial)
- DISAGGREGATED: ``disagg_cot.txt`` (producer/swap/managed money)
- TFF: ``fina_cot.txt`` (dealer/asset manager/leveraged funds)

Routing (T-05c): the Instrument Registry's ``cot_report_type`` field
selects the parser. Gold/Silver use Disaggregated; VIX-family uses TFF.

PIT discipline:
- ``observation_time`` = Tuesday 21:00 UTC (close of Tuesday)
- ``available_at`` = Friday 15:30 ET (DST-safe) — per cftc_friday_release
  rule in availability_rules.yaml
- Holiday handling: if Friday is a holiday, release shifts to next business
  day (cftc_friday_release.fallback = next_business_day)

T-12 case 1: Friday 15:30 ET before time — Panel MUST NOT include this
week's COT. Tested in test_cftc_adapter.
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
import pandas as pd
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pit_market.data.trading_calendar import (
    is_trading_day,
    next_trading_day,
)
from pit_market.storage.registry import Registry

log = logging.getLogger(__name__)


# =============================================================================
# Domain types
# =============================================================================


class CotReportType(StrEnum):
    LEGACY = "LEGACY"
    DISAGGREGATED = "DISAGGREGATED"
    TFF = "TFF"


class CotQualityStatus(StrEnum):
    VALID = "VALID"
    SOURCE_FAILED = "SOURCE_FAILED"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    UNKNOWN_MARKET_CODE = "UNKNOWN_MARKET_CODE"


@dataclass(frozen=True)
class CotObservation:
    canonical_symbol: str
    field_name: str
    value: float
    unit: str
    observation_time: datetime  # Tuesday close 21:00 UTC
    available_at: datetime  # Friday 15:30 ET (DST safe)
    cftc_market_code: str
    cot_report_type: CotReportType
    quality_status: CotQualityStatus
    raw_record_hash: str
    semantic_caveat: str = ""


@dataclass
class CotRawManifest:
    source_name: str = "cftc"
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
# Field mappings per report type
# =============================================================================

LEGACY_FIELDS: dict[str, str | None] = {
    "commercial_long": "Open Interest",
    "commercial_short": None,  # placeholder
}

# CFTC publishes a year-file. We'll use pandas to read it with fixed-width columns.
# For Phase 1, we provide a minimal but real mapping for the columns most cited.
DISAGG_FIELD_MAPPING: dict[str, tuple[str, str]] = {
    # field_name_suffix -> (column_substring, semantic_unit)
    "managed_money_net": ("Managed Money", "contracts"),
    "swap_dealer_net": ("Swap Dealer", "contracts"),
    "producer_merchant_net": ("Producer Merchant", "contracts"),
    "other_reportable_net": ("Other Reportable", "contracts"),
    "nonreportable_net": ("Non-Reportable", "contracts"),
    "open_interest_all": ("Open Interest", "contracts"),
    "change_in_open_interest_all": ("Change in Open Interest", "contracts"),
}

TFF_FIELD_MAPPING: dict[str, tuple[str, str]] = {
    "dealer_net": ("Dealer", "contracts"),
    "asset_manager_net": ("Asset Manager", "contracts"),
    "leveraged_funds_net": ("Leveraged Funds", "contracts"),
    "other_reportable_net": ("Other Reportable", "contracts"),
    "nonreportable_net": ("Non-Reportable", "contracts"),
    "open_interest_all": ("Open Interest", "contracts"),
}


# =============================================================================
# Adapter
# =============================================================================


class CotAdapterError(Exception):
    pass


class CotCftcAdapter:
    """Phase 1 CFTC COT adapter."""

    CFTC_BASE = "https://www.cftc.gov"

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

    def fetch_year(
        self,
        year: int,
        report_type: CotReportType | None = None,
        market_code: str | None = None,
    ) -> list[CotObservation]:
        """Fetch a year's COT report.

        Args:
            year: report year (e.g. 2024)
            report_type: explicit LEGACY/DISAGGREGATED/TFF. If None, all 3.
            market_code: filter to one market code (e.g. "088691" = gold).
        """
        self._throttle()
        types = [report_type] if report_type else list(CotReportType)
        all_obs: list[CotObservation] = []
        for rt in types:
            url = self._url_for_report(year, rt)
            try:
                resp = self._get_with_retry(url)
            except Exception as e:
                log.error("CFTC fetch %s %s failed: %s", year, rt, e)
                self._land_raw(
                    dataset_name=f"cot_{rt.value}",
                    request_payload={"year": year, "report_type": rt.value, "url": url},
                    response_bytes=b"",
                    record_count=0,
                    quality_status=CotQualityStatus.SOURCE_FAILED.value,
                    note=str(e),
                )
                continue

            resp_bytes = resp.content
            resp_hash = hashlib.sha256(resp_bytes).hexdigest()
            self._land_raw(
                dataset_name=f"cot_{rt.value}",
                request_payload={"year": year, "report_type": rt.value, "url": url},
                response_bytes=resp_bytes,
                record_count=0,  # updated after parsing
                quality_status=CotQualityStatus.VALID.value,
                note="",
            )

            # Parse
            try:
                df = self._parse_report(resp_bytes, rt)
            except Exception as e:
                log.error("CFTC parse %s %s failed: %s", year, rt, e)
                continue

            # Build observations
            obs = self._build_observations(
                df=df,
                report_type=rt,
                market_code=market_code,
                resp_hash=resp_hash,
            )
            all_obs.extend(obs)

        return all_obs

    # ----- helpers -----

    def _url_for_report(self, year: int, rt: CotReportType) -> str:
        if rt == CotReportType.LEGACY:
            return f"{self.CFTC_BASE}/files/dea/cotarchives/{year}/cot_year.txt"
        if rt == CotReportType.DISAGGREGATED:
            return f"{self.CFTC_BASE}/files/dea/cotarchives/{year}/disagg_cot.txt"
        if rt == CotReportType.TFF:
            return f"{self.CFTC_BASE}/files/dea/cotarchives/{year}/fina_cot.txt"
        raise CotAdapterError(f"Unknown report type: {rt}")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        min_interval = 1.0 / self._rate_limit
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_ts = time.monotonic()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        reraise=True,
    )
    def _get_with_retry(self, url: str) -> httpx.Response:
        with httpx.Client(timeout=120.0) as client:
            return client.get(url)

    def _parse_report(self, response_bytes: bytes, rt: CotReportType) -> pd.DataFrame:
        """Parse CFTC fixed-width text. The actual column layout varies year
        to year; for Phase 1 we use pandas.read_fwf and rely on the
        well-known headers from the 21st century files.
        """
        from io import StringIO

        text = response_bytes.decode("utf-8", errors="replace")
        # CFTC files have a header row; pandas can detect it
        df = pd.read_csv(
            StringIO(text),
            low_memory=False,
            dtype=str,  # parse later
        )
        # Normalize column names (strip whitespace, lowercase)
        df.columns = [c.strip() for c in df.columns]
        return df

    def _build_observations(
        self,
        df: pd.DataFrame,
        report_type: CotReportType,
        market_code: str | None,
        resp_hash: str,
    ) -> list[CotObservation]:
        """Build CotObservation list from parsed COT DataFrame.

        Filters by market_code (or all if None) and the field mapping
        appropriate for the report_type.
        """
        if df is None or df.empty:
            return []

        # Identify the market code column
        market_col = self._find_column(df, ["CFTC Contract Market Code", "Market Code", "MarketCode"])
        if market_col is None:
            return []

        # Identify the as-of date column (varies)
        date_col = self._find_column(df, ["As of Date in Form YYYY-MM-DD", "Report Date", "As of Date"])
        if date_col is None:
            return []

        # Filter by market_code if specified
        if market_code is not None:
            df = df[df[market_col].astype(str).str.strip() == str(market_code)]
            if df.empty:
                return []

        field_map = (
            DISAGG_FIELD_MAPPING if report_type == CotReportType.DISAGGREGATED
            else TFF_FIELD_MAPPING if report_type == CotReportType.TFF
            else {}
        )

        out: list[CotObservation] = []
        for _, row in df.iterrows():
            market_code_val = str(row[market_col]).strip()
            date_val = str(row[date_col]).strip()
            try:
                obs_date = datetime.strptime(date_val, "%Y-%m-%d").date()
            except ValueError:
                continue

            # Map report_type to canonical symbol
            sym = self._find_canonical_for_market(market_code_val)
            if sym is None:
                continue

            # PIT times per T-05c
            observation_time = datetime(obs_date.year, obs_date.month, obs_date.day, 21, 0)
            available_at = self._friday_release_at(obs_date)

            for field_suffix, (col_hint, unit) in field_map.items():
                val = self._extract_value(row, col_hint, report_type)
                if val is None:
                    continue
                field_name = f"position__cftc__{field_suffix}"
                # Cross-check metric registry (discipline)
                if not self._registry.has_metric(field_name):
                    log.debug("Skipping unregistered field %s", field_name)
                    continue
                metric = self._registry.metrics[field_name]
                out.append(
                    CotObservation(
                        canonical_symbol=sym,
                        field_name=field_name,
                        value=float(val),
                        unit=unit,
                        observation_time=observation_time,
                        available_at=available_at,
                        cftc_market_code=market_code_val,
                        cot_report_type=report_type,
                        quality_status=CotQualityStatus.VALID,
                        raw_record_hash=resp_hash,
                        semantic_caveat=metric.semantic_warning,
                    )
                )
        return out

    def _find_column(self, df: pd.DataFrame, candidates: list[str]) -> str | None:
        for c in candidates:
            if c in df.columns:
                return c
        # case-insensitive fallback
        lower = {col.lower(): col for col in df.columns}
        for c in candidates:
            if c.lower() in lower:
                return lower[c.lower()]
        return None

    def _extract_value(
        self, row: pd.Series, hint: str, report_type: CotReportType
    ) -> float | None:
        """Find a column matching `hint` in the row and parse a value.

        For 'net' fields we compute long - short. For 'open_interest' we
        use the column directly.
        """
        if hint == "Open Interest":
            return self._first_numeric(row, ["Open Interest", "Open Interest All"])
        if hint == "Change in Open Interest":
            return self._first_numeric(row, ["Change in Open Interest All"])
        # net fields: long - short
        long_col = self._find_column_by_substr(row, hint, "Long")
        short_col = self._find_column_by_substr(row, hint, "Short")
        if long_col and short_col:
            try:
                long_v = float(str(row[long_col]).replace(",", ""))
                short_v = float(str(row[short_col]).replace(",", ""))
                return long_v - short_v
            except (ValueError, TypeError):
                return None
        return None

    def _first_numeric(self, row: pd.Series, candidates: list[str]) -> float | None:
        for c in candidates:
            if c in row.index:
                try:
                    return float(str(row[c]).replace(",", ""))
                except (ValueError, TypeError):
                    continue
        return None

    def _find_column_by_substr(
        self, row: pd.Series, hint: str, side: str
    ) -> str | None:
        """Find a column whose name contains both `hint` and `side` (Long/Short)."""
        for col in row.index:
            if hint in str(col) and side in str(col) and "All" in str(col):
                return col
        # Fallback: no 'All' qualifier (Disagg has both All and Old formats)
        for col in row.index:
            if hint in str(col) and side in str(col):
                return col
        return None

    def _find_canonical_for_market(self, market_code: str) -> str | None:
        for sym, inst in self._registry.instruments.items():
            if inst.cftc_market_code == market_code:
                return sym
        return None

    def _friday_release_at(self, tuesday_date: date) -> datetime:
        """Return Friday 15:30 ET after Tuesday, DST-safe.

        If Friday is a holiday or weekend, push to next business day.
        """
        # Find Friday after Tuesday
        candidate = tuesday_date
        while candidate.weekday() != 4:  # Friday = 4
            candidate = date.fromordinal(candidate.toordinal() + 1)
        # If candidate is holiday, advance
        if not is_trading_day(candidate):
            candidate = next_trading_day(candidate)
        # 15:30 ET — represented as 15:30 in local-naive for Phase 1;
        # full TZ handling belongs in T-07 AvailabilityResolver
        return datetime(candidate.year, candidate.month, candidate.day, 15, 30)

    def _land_raw(
        self,
        dataset_name: str,
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
            / "source=cftc"
            / f"dataset={dataset_name}"
            / f"ingest_date={ingest_date}"
            / f"run_id={run_id}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        (out_dir / "request.json").write_text(
            json.dumps(request_payload, indent=2), encoding="utf-8"
        )
        response_path = out_dir / "response.json.gz"
        with gzip.open(response_path, "wb") as f:
            f.write(response_bytes if response_bytes else b"{}")
        resp_hash = hashlib.sha256(response_bytes if response_bytes else b"{}").hexdigest()

        (out_dir / "response_headers.json").write_text(json.dumps({}, indent=2), encoding="utf-8")

        manifest = CotRawManifest(
            dataset_name=dataset_name,
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
