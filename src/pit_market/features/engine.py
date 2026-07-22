"""Gold feature engine (TODO T-08).

Computes 4 feature groups from Silver observations:

- ``price_features``: returns, Z-scores, volatility
- ``flow_features``: short_ratio Z-scores
- ``macro_features``: yield curve spreads, percentile ranks
- ``positioning_features``: managed_money_net Z-scores

Discipline:
- Window length is config-driven (NOT hardcoded) — see ``window_configs``
  in ``config/metrics.yaml``. Window changes MUST bump ``feature_version``.
- ``quality_flags_json`` MUST inherit source ``semantic_warning``
  (discipline #7).
- Multi-source denominator prohibited: ``flow__finra__short_ratio``
  uses FINRA/FINRA only (R-11).
- Futures roll events: from T-05a ``detect_roll_events()``; mark
  ``roll_adjusted: false`` and use NaN for the roll-day return.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import polars as pl

from pit_market.ingestion.adapters.yfinance import RolloverEvent
from pit_market.normalization.silver import QualityStatus
from pit_market.storage.registry import Registry

log = logging.getLogger(__name__)


class FeatureGroup(StrEnum):
    PRICE = "price"
    FLOW = "flow"
    MACRO = "macro"
    POSITIONING = "positioning"


@dataclass
class FeatureConfig:
    """Resolved feature configuration (windows from metrics.yaml)."""

    short_term: int
    medium_term: int
    zscore_63d: int
    zscore_252d: int
    percentile_252d: int
    cot_lookback: int
    short_flow_lookback: int

    @property
    def config_hash(self) -> str:
        body = json.dumps(
            {
                "short_term": self.short_term,
                "medium_term": self.medium_term,
                "zscore_63d": self.zscore_63d,
                "zscore_252d": self.zscore_252d,
                "percentile_252d": self.percentile_252d,
                "cot_lookback": self.cot_lookback,
                "short_flow_lookback": self.short_flow_lookback,
            },
            sort_keys=True,
        )
        return hashlib.sha256(body.encode()).hexdigest()[:16]

    @classmethod
    def from_registry(cls, registry: Registry) -> FeatureConfig:
        # We re-read raw yaml for window_configs; the registry metrics store
        # in extra. Use the same loader.
        import yaml
        cfg_path = Path(registry._registry_paths if hasattr(registry, "_registry_paths") else "config/metrics.yaml")
        # If registry doesn't expose paths, load via the configured path
        try:
            raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # Fallback: defaults
            return cls(5, 21, 63, 252, 252, 13, 21)
        wc = raw.get("window_configs", {})
        return cls(
            short_term=int(wc.get("short_term", 5)),
            medium_term=int(wc.get("medium_term", 21)),
            zscore_63d=int(wc.get("zscore_63d", 63)),
            zscore_252d=int(wc.get("zscore_252d", 252)),
            percentile_252d=int(wc.get("percentile_252d", 252)),
            cot_lookback=int(wc.get("cot_lookback", 13)),
            short_flow_lookback=int(wc.get("short_flow_lookback", 21)),
        )


@dataclass
class FeatureOutput:
    feature_observation_id: str
    canonical_symbol: str
    field_name: str
    value: float | None
    unit: str
    feature_time: datetime
    available_at: datetime
    feature_definition_id: str
    feature_version: str
    configuration_hash: str
    input_observation_ids: list[str]
    input_max_available_at: datetime
    quality_status: QualityStatus
    quality_flags: dict[str, Any] = field(default_factory=dict)


class FeatureEngine:
    """Compute features from Silver observations."""

    def __init__(self, registry: Registry, config: FeatureConfig | None = None) -> None:
        self._registry = registry
        self._config = config or FeatureConfig.from_registry(registry)
        self._feature_version = f"features.v1.{self._config.config_hash}"

    @property
    def feature_version(self) -> str:
        return self._feature_version

    # ----- price features -----

    def compute_return_zscore(
        self,
        symbol: str,
        silver_df: pl.DataFrame,
        window: int | None = None,
        roll_events: list[RolloverEvent] | None = None,
    ) -> list[FeatureOutput]:
        """Compute daily return Z-score over a rolling window.

        Returns NaN for roll days (T-05a ``detect_roll_events()`` output).
        ``quality_flags`` includes ``roll_adjusted: false`` for those rows.
        """
        if window is None:
            window = self._config.zscore_63d
        definition_id = f"price_return_zscore_{window}d.v1"

        # Filter to price__yf__close RAW_CLOSE rows for this symbol
        sub = silver_df.filter(
            (pl.col("canonical_symbol") == symbol)
            & (pl.col("field_name") == "price__yf__close")
            & (pl.col("price_type") == "RAW_CLOSE")
        ).sort("observation_time")

        if sub.is_empty() or len(sub) < window:
            return []

        # Get the underlying source semantic_warning
        source_metric = self._registry.metrics["price__yf__close"]
        semantic_warning = source_metric.semantic_warning

        out: list[FeatureOutput] = []
        prices = sub["value"].to_list()
        times = sub["observation_time"].to_list()
        avail = sub["available_at"].to_list()
        obs_ids = sub["observation_id"].to_list()
        sub["quality_flags_json"].to_list()
        roll_dates = {e.observation_time.date() for e in (roll_events or [])}

        for i in range(window, len(prices)):
            window_prices = [p for p in prices[i - window:i] if p is not None and not (isinstance(p, float) and p != p)]
            if len(window_prices) < window - 5:  # allow some NaN
                continue
            cur = prices[i]
            if cur is None or (isinstance(cur, float) and cur != cur):
                continue
            mean = sum(window_prices) / len(window_prices)
            var = sum((p - mean) ** 2 for p in window_prices) / len(window_prices)
            std = var ** 0.5
            z = (cur - mean) / std if std > 0 else 0.0

            # Roll day: NaN + roll_adjusted: false
            obs_date = times[i].date() if hasattr(times[i], "date") else times[i]
            if obs_date in roll_dates:
                z = None
                roll_adjusted = False
            else:
                roll_adjusted = True

            # Inherit source semantic_warning (discipline #7)
            flags = {
                "roll_adjusted": roll_adjusted,
                "window": window,
                "source_semantic_warning": semantic_warning,
            }
            out.append(
                FeatureOutput(
                    feature_observation_id=f"feat_{symbol}_{definition_id}_{obs_date.isoformat()}",
                    canonical_symbol=symbol,
                    field_name=f"price__yf__return_1d__zscore__{window}d",
                    value=z,
                    unit="zscore",
                    feature_time=times[i],
                    available_at=avail[i],
                    feature_definition_id=definition_id,
                    feature_version=self._feature_version,
                    configuration_hash=self._config.config_hash,
                    input_observation_ids=obs_ids[i - window:i + 1],
                    input_max_available_at=max(avail[i - window:i + 1]),
                    quality_status=QualityStatus.VALID,
                    quality_flags=flags,
                )
            )
        return out

    # ----- flow features -----

    def compute_short_ratio_zscore(
        self, symbol: str, silver_df: pl.DataFrame, window: int | None = None
    ) -> list[FeatureOutput]:
        """Compute Z-score of FINRA short_ratio. Multi-source denominator
        is PROHIBITED — this only operates on FINRA-sourced rows.
        """
        if window is None:
            window = self._config.zscore_63d
        definition_id = f"short_ratio_zscore_{window}d.v1"

        sub = silver_df.filter(
            (pl.col("canonical_symbol") == symbol)
            & (pl.col("field_name") == "flow__finra__short_ratio")
            & (pl.col("source_name") == "finra")  # multi-source discipline
        ).sort("observation_time")

        if sub.is_empty() or len(sub) < window:
            return []

        source_metric = self._registry.metrics["flow__finra__short_ratio"]
        semantic_warning = source_metric.semantic_warning  # "非全市场"

        out: list[FeatureOutput] = []
        ratios = sub["value"].to_list()
        times = sub["observation_time"].to_list()
        avail = sub["available_at"].to_list()
        obs_ids = sub["observation_id"].to_list()

        for i in range(window, len(ratios)):
            window_vals = [
                r for r in ratios[i - window:i]
                if r is not None and not (isinstance(r, float) and r != r)
            ]
            if len(window_vals) < window - 5:
                continue
            cur = ratios[i]
            if cur is None or (isinstance(cur, float) and cur != cur):
                continue
            mean = sum(window_vals) / len(window_vals)
            var = sum((r - mean) ** 2 for r in window_vals) / len(window_vals)
            std = var ** 0.5
            z = (cur - mean) / std if std > 0 else 0.0
            obs_date = times[i].date() if hasattr(times[i], "date") else times[i]
            out.append(
                FeatureOutput(
                    feature_observation_id=f"feat_{symbol}_{definition_id}_{obs_date.isoformat()}",
                    canonical_symbol=symbol,
                    field_name=f"flow__finra__short_ratio__zscore__{window}d",
                    value=z,
                    unit="zscore",
                    feature_time=times[i],
                    available_at=avail[i],
                    feature_definition_id=definition_id,
                    feature_version=self._feature_version,
                    configuration_hash=self._config.config_hash,
                    input_observation_ids=obs_ids[i - window:i + 1],
                    input_max_available_at=max(avail[i - window:i + 1]),
                    quality_status=QualityStatus.VALID,
                    quality_flags={
                        "window": window,
                        "source_semantic_warning": semantic_warning,
                    },
                )
            )
        return out
