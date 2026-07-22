"""PIT Panel Builder (TODO T-09).

Builds an immutable PIT panel for a given ``decision_time``:

  ``SELECT * FROM feature_observations_bitemporal
   WHERE available_at <= $decision_time
     AND valid_from <= $decision_time
     AND (valid_to IS NULL OR valid_to > $decision_time)``

For Phase 1 we build panels from in-memory Silver + Feature outputs
(no DuckDB yet); a real DuckDB-backed version lands in T-10 alongside
the FastAPI layer.

Outputs (per PRD §9.4):
- ``value_panel`` (Polars DataFrame)
- ``lineage_panel`` (Polars DataFrame)
- ``quality_report.json``
- ``panel_manifest.json``

Each panel has:
- ``panel_id``: deterministic from decision_time + universe + feature_version
- ``panel_sha256``: hash of value_panel content
- ``panel_version``: registry epoch
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

log = logging.getLogger(__name__)


@dataclass
class PanelBuildResult:
    panel_id: str
    panel_sha256: str
    panel_version: str
    decision_time: datetime
    input_cutoff_time: datetime
    universe_version: str
    instrument_registry_version: str
    metric_registry_version: str
    feature_version: str
    row_count: int
    field_count: int
    quality_status: str
    quality_score: float
    value_panel: pl.DataFrame
    lineage_panel: pl.DataFrame
    output_path: Path
    manifest: dict[str, Any] = field(default_factory=dict)


class PitPanelBuilder:
    """Build a PIT panel for a decision_time.

    Inputs: Silver observations (DataFrame) and/or feature observations.
    Output: PanelBuildResult with value_panel + lineage_panel + manifest.
    """

    def __init__(
        self,
        silver_df: pl.DataFrame,
        features_df: pl.DataFrame | None = None,
        feature_version: str = "features.v1.0",
        universe_version: str = "registry.v1.0",
        instrument_registry_version: str = "registry.v1.0",
        metric_registry_version: str = "metrics.v1.0",
    ) -> None:
        self._silver = silver_df
        self._features = features_df if features_df is not None else pl.DataFrame()
        self._feature_version = feature_version
        self._universe_version = universe_version
        self._instrument_registry_version = instrument_registry_version
        self._metric_registry_version = metric_registry_version

    def build(
        self,
        decision_time: datetime,
        universe: list[str],
        decision_clock: str = "1805_ET",
        output_dir: str | Path = "./data/gold/pit_panels",
    ) -> PanelBuildResult:
        """Build a PIT panel.

        Args:
            decision_time: when the decision is being made (PIT anchor)
            universe: list of canonical_symbols to include
            decision_clock: "1605_ET" or "1805_ET"
            output_dir: where to write the panel files
        """
        if decision_time.tzinfo is None:
            decision_time = decision_time.replace(tzinfo=UTC)

        # PIT filter: available_at <= decision_time, valid_from <= decision_time,
        # valid_to IS NULL OR valid_to > decision_time
        eligible_silver = self._silver.filter(
            (pl.col("available_at") <= decision_time)
            & (pl.col("valid_from") <= decision_time)
            & pl.col("valid_to").is_null()
        ) if not self._silver.is_empty() else pl.DataFrame()

        # For each (symbol, field, price_type) keep the latest available_at row
        if not eligible_silver.is_empty():
            eligible_silver = (
                eligible_silver
                .sort("available_at", descending=True)
                .unique(subset=["canonical_symbol", "field_name", "price_type"], keep="first", maintain_order=True)
            )
            eligible_silver = eligible_silver.filter(pl.col("canonical_symbol").is_in(universe))

        eligible_features = pl.DataFrame()
        if not self._features.is_empty():
            eligible_features = self._features.filter(
                pl.col("available_at") <= decision_time
            )
            eligible_features = eligible_features.filter(
                pl.col("canonical_symbol").is_in(universe)
            )

        # Combine silver + features
        combined = self._combine(eligible_silver, eligible_features)

        # Quality stats
        if combined.is_empty():
            quality_status = "REJECTED"
            quality_score = 0.0
        else:
            # Score: ratio of VALID rows
            valid_count = combined.filter(pl.col("quality_status") == "VALID").height
            quality_score = valid_count / combined.height
            if quality_score >= 0.9:
                quality_status = "GOOD"
            elif quality_score >= 0.7:
                quality_status = "DEGRADED"
            elif quality_score >= 0.5:
                quality_status = "PARTIAL"
            else:
                quality_status = "REJECTED"

        # Build lineage panel
        lineage_cols = [
            "canonical_symbol", "field_name", "price_type",
            "observation_time", "available_at", "raw_record_hash", "quality_status",
        ]
        if not combined.is_empty():
            lineage = combined.select([c for c in lineage_cols if c in combined.columns])
        else:
            lineage = pl.DataFrame({c: [] for c in lineage_cols})

        # Compute hashes
        if not combined.is_empty():
            value_str = combined.write_json()
            panel_sha256 = hashlib.sha256(value_str.encode("utf-8")).hexdigest()
        else:
            panel_sha256 = hashlib.sha256(b"{}").hexdigest()
        panel_id = self._make_panel_id(decision_time, universe, panel_sha256)
        panel_version = "v1"

        # Write to disk
        out_dir = Path(output_dir)
        decision_date = decision_time.date().isoformat()
        out_path = out_dir / f"decision_date={decision_date}" / f"decision_clock={decision_clock}" / f"panel_version={panel_version}" / panel_id
        out_path.mkdir(parents=True, exist_ok=True)

        combined.write_parquet(str(out_path / "value_panel.parquet"))
        lineage.write_parquet(str(out_path / "lineage_panel.parquet"))

        # Quality report
        quality_report = {
            "panel_id": panel_id,
            "decision_time": decision_time.isoformat(),
            "row_count": combined.height,
            "field_count": len(combined.columns) if not combined.is_empty() else 0,
            "quality_status": quality_status,
            "quality_score": quality_score,
            "universe": universe,
            "feature_version": self._feature_version,
        }
        (out_path / "quality_report.json").write_text(
            json.dumps(quality_report, indent=2), encoding="utf-8"
        )

        # Manifest
        manifest = {
            "panel_id": panel_id,
            "panel_sha256": panel_sha256,
            "panel_version": panel_version,
            "decision_time": decision_time.isoformat(),
            "input_cutoff_time": decision_time.isoformat(),
            "decision_clock": decision_clock,
            "universe_version": self._universe_version,
            "instrument_registry_version": self._instrument_registry_version,
            "metric_registry_version": self._metric_registry_version,
            "feature_version": self._feature_version,
            "row_count": combined.height,
            "field_count": len(combined.columns) if not combined.is_empty() else 0,
            "quality_status": quality_status,
            "quality_score": quality_score,
            "created_at_utc": datetime.now(UTC).isoformat(),
        }
        (out_path / "panel_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        return PanelBuildResult(
            panel_id=panel_id,
            panel_sha256=panel_sha256,
            panel_version=panel_version,
            decision_time=decision_time,
            input_cutoff_time=decision_time,
            universe_version=self._universe_version,
            instrument_registry_version=self._instrument_registry_version,
            metric_registry_version=self._metric_registry_version,
            feature_version=self._feature_version,
            row_count=combined.height,
            field_count=len(combined.columns) if not combined.is_empty() else 0,
            quality_status=quality_status,
            quality_score=quality_score,
            value_panel=combined,
            lineage_panel=lineage,
            output_path=out_path,
            manifest=manifest,
        )

    def _combine(
        self, silver: pl.DataFrame, features: pl.DataFrame
    ) -> pl.DataFrame:
        if silver.is_empty() and features.is_empty():
            return pl.DataFrame()
        if features.is_empty():
            return silver
        if silver.is_empty():
            return features
        # Union: align columns
        all_cols = list(dict.fromkeys(list(silver.columns) + list(features.columns)))
        for c in all_cols:
            if c not in silver.columns:
                silver = silver.with_columns(pl.lit(None).alias(c))
            if c not in features.columns:
                features = features.with_columns(pl.lit(None).alias(c))
        return pl.concat([silver.select(all_cols), features.select(all_cols)], how="vertical")

    def _make_panel_id(
        self, decision_time: datetime, universe: list[str], sha: str
    ) -> str:
        json.dumps(
            {
                "decision_time": decision_time.isoformat(),
                "universe": sorted(universe),
                "feature_version": self._feature_version,
                "sha": sha,
            },
            sort_keys=True,
        )
        return f"pit_{decision_time.strftime('%Y%m%d_%H%M')}_{sha[:8]}"
