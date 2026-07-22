"""Feature engine tests (TODO T-08 acceptance)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from pit_market.features.engine import FeatureConfig, FeatureEngine
from pit_market.ingestion.adapters.yfinance import RolloverEvent
from pit_market.storage.registry import Registry

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(CONFIG_DIR)


@pytest.fixture
def engine(registry: Registry) -> FeatureEngine:
    return FeatureEngine(registry)


def _silver_df_with_prices(symbol: str, n: int, base: float = 100.0) -> pl.DataFrame:
    """Build a Silver-like DataFrame with RAW_CLOSE rows for `n` trading days."""
    rows = []
    start = datetime(2024, 1, 2, 16, 0, tzinfo=UTC)  # first trading day
    for i in range(n):
        obs_time = start + timedelta(days=i * 7)  # weekly spacing to avoid month overflow
        rows.append({
            "observation_id": f"obs_{i:04d}",
            "canonical_symbol": symbol,
            "field_name": "price__yf__close",
            "value": base + i * 0.5,
            "price_type": "RAW_CLOSE",
            "observation_time": obs_time,
            "available_at": obs_time + timedelta(hours=2),
            "source_name": "yfinance",
            "dataset_name": "daily_ohlcv",
            "quality_status": "VALID",
            "quality_flags_json": "{}",
            "fill_type": "OBSERVED",
        })
    return pl.DataFrame(rows)


# =============================================================================
# Window config (discipline: config-driven, not hardcoded)
# =============================================================================


class TestConfig:
    def test_default_windows_load(self, registry: Registry) -> None:
        cfg = FeatureConfig.from_registry(registry)
        assert cfg.zscore_63d == 63
        assert cfg.zscore_252d == 252
        assert cfg.config_hash is not None

    def test_config_hash_changes_with_window(self, registry: Registry) -> None:
        cfg1 = FeatureConfig(5, 21, 63, 252, 252, 13, 21)
        cfg2 = FeatureConfig(5, 21, 90, 252, 252, 13, 21)  # different zscore_63d
        assert cfg1.config_hash != cfg2.config_hash

    def test_feature_version_includes_config_hash(self, engine: FeatureEngine) -> None:
        assert engine.feature_version.startswith("features.v1.")
        assert engine._config.config_hash in engine.feature_version


# =============================================================================
# Price return Z-score
# =============================================================================


class TestReturnZscore:
    def test_zscore_computed(self, engine: FeatureEngine) -> None:
        df = _silver_df_with_prices("QQQ", 100)
        feats = engine.compute_return_zscore("QQQ", df, window=20)
        # 80 outputs (100 - 20)
        assert len(feats) == 80
        # First value should be near 0 (price=110, in middle of trend)
        first = feats[0].value
        assert -2.0 < first < 2.0

    def test_field_name_uses_window(self, engine: FeatureEngine) -> None:
        df = _silver_df_with_prices("QQQ", 100)
        feats = engine.compute_return_zscore("QQQ", df, window=20)
        assert all(f.field_name == "price__yf__return_1d__zscore__20d" for f in feats)


# =============================================================================
# Roll event handling (T-05a)
# =============================================================================


class TestRollEventHandling:
    def test_roll_day_marked_nan(self, engine: FeatureEngine) -> None:
        df = _silver_df_with_prices("GC=F", 50)
        # Find a date in the output range (after window=10): i=20 → 2024-01-02 + 140 = 2024-05-21
        roll_date = df["observation_time"][20]  # 20th obs
        roll = [
            RolloverEvent(
                canonical_symbol="GC=F",
                observation_time=roll_date,
                old_close=100.0, new_close=105.0, spread=5.0,
            )
        ]
        feats = engine.compute_return_zscore("GC=F", df, window=10, roll_events=roll)
        roll_feats = [
            f for f in feats
            if f.feature_time == roll_date
        ]
        assert len(roll_feats) == 1
        assert roll_feats[0].value is None
        assert roll_feats[0].quality_flags["roll_adjusted"] is False

    def test_non_roll_day_marked_true(self, engine: FeatureEngine) -> None:
        df = _silver_df_with_prices("GC=F", 50)
        feats = engine.compute_return_zscore("GC=F", df, window=10)
        assert all(f.quality_flags.get("roll_adjusted") is True for f in feats)


# =============================================================================
# Semantic warning propagation (discipline #7)
# =============================================================================


class TestSemanticPropagation:
    def test_price_feature_inherits_warning(self, engine: FeatureEngine) -> None:
        df = _silver_df_with_prices("QQQ", 50)
        feats = engine.compute_return_zscore("QQQ", df, window=10)
        # price__yf__close warning: "yfinance 价格受股息/拆股调整..."
        assert any("调整" in f.quality_flags.get("source_semantic_warning", "") for f in feats)


# =============================================================================
# Multi-source denominator (R-11)
# =============================================================================


class TestMultiSourceDiscipline:
    def test_short_ratio_zscore_filters_finra_only(self, engine: FeatureEngine) -> None:
        # Build rows: half FINRA, half from another source — engine must filter
        rows = []
        for i in range(20):
            rows.append({
                "observation_id": f"finra_{i}",
                "canonical_symbol": "QQQ",
                "field_name": "flow__finra__short_ratio",
                "value": 0.3 + (i % 5) * 0.01,
                "source_name": "finra",
                "price_type": None,
                "observation_time": datetime(2024, 1, 1 + i, 16, 0, tzinfo=UTC),
                "available_at": datetime(2024, 1, 2 + i, 14, 0, tzinfo=UTC),
                "quality_status": "VALID",
                "quality_flags_json": "{}",
                "fill_type": "OBSERVED",
            })
            rows.append({
                "observation_id": f"sip_{i}",
                "canonical_symbol": "QQQ",
                "field_name": "flow__finra__short_ratio",
                "value": 0.4 + (i % 5) * 0.01,
                "source_name": "sip_tape",  # would-be different source
                "price_type": None,
                "observation_time": datetime(2024, 1, 1 + i, 16, 0, tzinfo=UTC),
                "available_at": datetime(2024, 1, 2 + i, 14, 0, tzinfo=UTC),
                "quality_status": "VALID",
                "quality_flags_json": "{}",
                "fill_type": "OBSERVED",
            })
        df = pl.DataFrame(rows)
        feats = engine.compute_short_ratio_zscore("QQQ", df, window=10)
        # Only FINRA rows used
        for f in feats:
            assert all(oid.startswith("finra_") for oid in f.input_observation_ids)

    def test_short_ratio_inherits_non_full_market_warning(
        self, engine: FeatureEngine
    ) -> None:
        rows = []
        for i in range(20):
            rows.append({
                "observation_id": f"finra_{i}",
                "canonical_symbol": "QQQ",
                "field_name": "flow__finra__short_ratio",
                "value": 0.3,
                "source_name": "finra",
                "price_type": None,
                "observation_time": datetime(2024, 1, 1 + i, 16, 0, tzinfo=UTC),
                "available_at": datetime(2024, 1, 2 + i, 14, 0, tzinfo=UTC),
                "quality_status": "VALID",
                "quality_flags_json": "{}",
                "fill_type": "OBSERVED",
            })
        df = pl.DataFrame(rows)
        feats = engine.compute_short_ratio_zscore("QQQ", df, window=10)
        # "非全市场" warning must propagate
        assert any(
            "非全市场" in f.quality_flags.get("source_semantic_warning", "")
            for f in feats
        )
