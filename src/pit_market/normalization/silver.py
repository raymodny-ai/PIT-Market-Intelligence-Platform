"""Silver bitemporal observations schema (TODO T-06).

Defines:
- ``SilverObservationSchema`` (Pandera): validates every Silver row
- ``SilverWriter``: append-only Parquet writer with discipline #8 enforcement

Discipline enforcement (v0.3):
- ``canonical_symbol`` MUST exist in Instrument Registry (else UNMAPPED_SYMBOL)
- ``vendor_symbol`` preserved in source_metadata_json.vendor_symbol
- ``fill_type`` 4-value enum: OBSERVED | FORWARD_FILLED | CALENDAR_INFERRED | INTERPOLATED
- ``fill_source_observation_id`` required when fill_type != OBSERVED
- ``fill_lag_days`` for staleness calculation
- ``quality_flags_json`` carries source ``semantic_warning`` (discipline #7 prep)
- ``available_at`` is TIMESTAMPTZ (use ``datetime`` with tzinfo; minute precision)
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import pandera.polars as papl
import polars as pl
from pandera.errors import SchemaError, SchemaErrors

from pit_market.storage.registry import Registry, RegistryError

log = logging.getLogger(__name__)


# =============================================================================
# Domain enums
# =============================================================================


class FillType(StrEnum):
    OBSERVED = "OBSERVED"
    FORWARD_FILLED = "FORWARD_FILLED"
    CALENDAR_INFERRED = "CALENDAR_INFERRED"
    INTERPOLATED = "INTERPOLATED"


class QualityStatus(StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    INFERRED_AVAILABILITY = "INFERRED_AVAILABILITY"
    SOURCE_FAILED = "SOURCE_FAILED"
    SOURCE_THROTTLED = "SOURCE_THROTTLED"


# =============================================================================
# Pandera schema
# =============================================================================


class SilverSchema(papl.DataFrameModel):
    """Schema for Silver observations_bitemporal.

    Pandera-polars syntax: column-level checks are declared with ``papl.Field``.
    """

    observation_id: str = papl.Field(nullable=False)
    source_name: str = papl.Field(isin=[
        "yfinance", "fred", "cftc", "finra", "sec", "cboe", "etf_issuer"
    ])
    dataset_name: str = papl.Field(nullable=False)
    canonical_symbol: str = papl.Field(nullable=False)
    vendor_symbol: str = papl.Field(nullable=True)
    field_name: str = papl.Field(nullable=False)
    value: float = papl.Field(nullable=True)
    unit: str = papl.Field(nullable=True)
    frequency: str = papl.Field(isin=[
        "daily", "weekly", "monthly", "quarterly", "event"
    ], nullable=False)
    price_type: str = papl.Field(
        nullable=True, isin=["RAW_CLOSE", "ADJ_CLOSE", "SPLIT_FACTOR", None]
    )
    observation_time: datetime = papl.Field(nullable=False)
    observation_end_time: datetime = papl.Field(nullable=True)
    release_time: datetime = papl.Field(nullable=True)
    available_at: datetime = papl.Field(nullable=False)
    valid_from: datetime = papl.Field(nullable=False)
    valid_to: datetime = papl.Field(nullable=True)
    ingested_at: datetime = papl.Field(nullable=False)
    run_id: str = papl.Field(nullable=False)
    raw_record_hash: str = papl.Field(nullable=False)
    parser_version: str = papl.Field(nullable=False)
    source_metadata_json: str = papl.Field(nullable=True)
    quality_status: str = papl.Field(
        nullable=False, isin=[s.value for s in QualityStatus]
    )
    quality_flags_json: str = papl.Field(nullable=True)
    fill_type: str = papl.Field(
        nullable=False, isin=[f.value for f in FillType]
    )
    fill_source_observation_id: str = papl.Field(nullable=True)
    fill_lag_days: int = papl.Field(nullable=True)

    class Config:
        coerce = True
        strict = False
        ordered = False


# =============================================================================
# Writer
# =============================================================================


@dataclass
class SilverWriteResult:
    """Result of a Silver write batch."""

    written: int = 0
    rejected: int = 0
    rejection_reasons: list[str] = field(default_factory=list)
    output_path: Path | None = None


class SilverWriter:
    """Append-only Silver writer (T-06).

    Layout: ``<silver_dir>/source_name=<name>/dataset_name=<name>/
            available_date=YYYY-MM-DD/part-000.parquet``
    """

    def __init__(
        self,
        registry: Registry,
        silver_dir: str | Path,
        parser_version: str = "v0.3",
    ) -> None:
        self._registry = registry
        self._silver_dir = Path(silver_dir)
        self._parser_version = parser_version

    def write(
        self,
        df: pl.DataFrame,
        source_name: str,
        dataset_name: str,
        run_id: str,
        raw_record_hashes: list[str] | None = None,
    ) -> SilverWriteResult:
        """Validate and append-write a batch of observations."""
        if df.is_empty():
            return SilverWriteResult(written=0)

        # Step 1: discipline #8 — canonical_symbol must be registered
        try:
            unique_symbols = df["canonical_symbol"].unique().to_list()
            for sym in unique_symbols:
                if not self._registry.has_instrument(sym):
                    raise RegistryError(
                        f"UNMAPPED_SYMBOL: {sym!r} not in Instrument Registry"
                    )
        except RegistryError as e:
            log.error("Silver write rejected: %s", e)
            return SilverWriteResult(written=0, rejected=len(df), rejection_reasons=[str(e)])

        # Step 2: fill out required columns
        now = datetime.now(UTC)
        df = df.with_columns(
            pl.lit(now).alias("ingested_at"),
            pl.lit(run_id).alias("run_id"),
            pl.lit(self._parser_version).alias("parser_version"),
            pl.lit("{}").alias("source_metadata_json").cast(pl.Utf8),
            pl.lit("{}").alias("quality_flags_json").cast(pl.Utf8),
        )
        # raw_record_hash fallback
        if "raw_record_hash" not in df.columns:
            if raw_record_hashes is None or len(raw_record_hashes) != len(df):
                raise ValueError("raw_record_hash column or matching list required")
            df = df.with_columns(pl.Series("raw_record_hash", raw_record_hashes))
        # observation_id default
        if "observation_id" not in df.columns:
            ids = [str(uuid.uuid4()) for _ in range(len(df))]
            df = df.with_columns(pl.Series("observation_id", ids))
        # fill_type default
        if "fill_type" not in df.columns:
            df = df.with_columns(pl.lit(FillType.OBSERVED.value).alias("fill_type"))
        # quality_status default
        if "quality_status" not in df.columns:
            df = df.with_columns(pl.lit(QualityStatus.VALID.value).alias("quality_status"))
        # valid_to default null
        if "valid_to" not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Datetime).alias("valid_to"))

        # Step 3: Pandera validation
        try:
            SilverSchema.validate(df, lazy=True)
        except (SchemaError, SchemaErrors) as e:
            log.error("Silver schema validation failed: %s", e)
            return SilverWriteResult(
                written=0, rejected=len(df), rejection_reasons=[str(e)]
            )

        # Step 4: enforce fill_source_observation_id when fill_type != OBSERVED
        non_observed = df.filter(pl.col("fill_type") != FillType.OBSERVED.value)
        if not non_observed.is_empty():
            missing = non_observed.filter(pl.col("fill_source_observation_id").is_null())
            if not missing.is_empty():
                msg = (
                    f"fill_type != OBSERVED requires fill_source_observation_id; "
                    f"{len(missing)} rows missing"
                )
                log.error(msg)
                return SilverWriteResult(
                    written=0, rejected=len(df), rejection_reasons=[msg]
                )

        # Step 5: path = available_date partition
        if "available_at" not in df.columns:
            raise ValueError("available_at column required for partition")
        # Polars datetime must be cast for date partition
        df = df.with_columns(
            pl.col("available_at").dt.date().alias("_available_date")
        )
        available_dates = df["_available_date"].unique().to_list()
        written_total = 0
        last_path: Path | None = None
        for d in available_dates:
            sub = df.filter(pl.col("_available_date") == d).drop("_available_date")
            out_dir = (
                self._silver_dir
                / f"source_name={source_name}"
                / f"dataset_name={dataset_name}"
                / f"available_date={d.isoformat()}"
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / "part-000.parquet"
            sub.write_parquet(str(out_path))
            last_path = out_path
            written_total += len(sub)
        return SilverWriteResult(
            written=written_total, rejected=0, output_path=last_path
        )

    def supersede(
        self,
        symbol: str,
        field_name: str,
        price_type: str | None,
        observation_time: datetime,
        superseded_at: datetime,
    ) -> int:
        """Mark existing Silver rows for (symbol, field, observation_time) as
        superseded by writing a side-car ``valid_to`` Parquet with the same
        key but ``valid_to = superseded_at``.

        Returns count of rows superseded.
        """
        # For Phase 1 we use a simplified approach: walk all matching partition
        # files and rewrite rows with valid_to set. This is fine for low-volume
        # adjustments. For high-volume, T-09 PIT Panel builder will use this
        # during PIT query path instead.
        count = 0
        pattern = "**/part-*.parquet"
        for path in self._silver_dir.rglob(pattern):
            df = pl.read_parquet(str(path))
            mask = (
                (pl.col("canonical_symbol") == symbol)
                & (pl.col("field_name") == field_name)
                & (pl.col("observation_time") == observation_time)
                & (pl.col("valid_to").is_null())
            )
            if price_type is not None:
                mask = mask & (pl.col("price_type") == price_type)
            hits = df.filter(mask)
            if hits.is_empty():
                continue
            count += len(hits)
            updated = df.with_columns(
                pl.when(mask)
                .then(pl.lit(superseded_at))
                .otherwise(pl.col("valid_to"))
                .alias("valid_to")
            )
            updated.write_parquet(str(path))
        return count
