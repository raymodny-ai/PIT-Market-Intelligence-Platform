"""PIT Panel Builder tests (TODO T-09 acceptance)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from pit_market.pit.builder import PitPanelBuilder


def _silver_rows(symbols: list[str], n_per: int = 5) -> pl.DataFrame:
    rows = []
    base_time = datetime(2024, 1, 1, 16, 0, tzinfo=UTC)
    for sym_i, sym in enumerate(symbols):
        for i in range(n_per):
            obs_time = base_time.replace(day=1 + i * 7)
            avail = obs_time.replace(hour=18)
            rows.append({
                "observation_id": f"obs_{sym_i}_{i}",
                "canonical_symbol": sym,
                "field_name": "price__yf__close",
                "value": 100.0 + i,
                "price_type": "RAW_CLOSE",
                "observation_time": obs_time,
                "available_at": avail,
                "valid_from": obs_time,
                "valid_to": None,
                "source_name": "yfinance",
                "dataset_name": "daily_ohlcv",
                "quality_status": "VALID",
                "quality_flags_json": "{}",
                "fill_type": "OBSERVED",
                "raw_record_hash": f"hash_{sym_i}_{i}",
            })
    return pl.DataFrame(rows)


class TestBasicBuild:
    def test_build_minimal(self, tmp_path: Path) -> None:
        silver = _silver_rows(["QQQ", "SPY"], 3)
        builder = PitPanelBuilder(silver_df=silver)
        result = builder.build(
            decision_time=datetime(2024, 1, 15, 18, 0, tzinfo=UTC),
            universe=["QQQ", "SPY"],
            output_dir=tmp_path,
        )
        assert result.row_count > 0
        assert result.quality_status in {"GOOD", "DEGRADED", "PARTIAL", "REJECTED"}
        assert (result.output_path / "value_panel.parquet").exists()
        assert (result.output_path / "lineage_panel.parquet").exists()
        assert (result.output_path / "quality_report.json").exists()
        assert (result.output_path / "panel_manifest.json").exists()

    def test_universe_filter(self, tmp_path: Path) -> None:
        silver = _silver_rows(["QQQ", "SPY", "GLD"], 3)
        builder = PitPanelBuilder(silver_df=silver)
        result = builder.build(
            decision_time=datetime(2024, 1, 15, 18, 0, tzinfo=UTC),
            universe=["QQQ"],  # only QQQ
            output_dir=tmp_path,
        )
        assert "QQQ" in result.value_panel["canonical_symbol"].unique().to_list()
        assert "SPY" not in result.value_panel["canonical_symbol"].unique().to_list()
        assert "GLD" not in result.value_panel["canonical_symbol"].unique().to_list()


class TestPitCausality:
    def test_future_available_excluded(self, tmp_path: Path) -> None:
        """T-12 case 4: available_at > decision_time MUST be excluded."""
        silver = _silver_rows(["QQQ"], 3)
        builder = PitPanelBuilder(silver_df=silver)
        # decision_time = 2024-01-01 12:00 — BEFORE first available_at 18:00
        result = builder.build(
            decision_time=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            universe=["QQQ"],
            output_dir=tmp_path,
        )
        # No rows should pass since all available_at are 18:00 on observation day
        assert result.row_count == 0

    def test_past_available_included(self, tmp_path: Path) -> None:
        silver = _silver_rows(["QQQ"], 3)
        builder = PitPanelBuilder(silver_df=silver)
        result = builder.build(
            decision_time=datetime(2024, 2, 1, 12, 0, tzinfo=UTC),
            universe=["QQQ"],
            output_dir=tmp_path,
        )
        # All 3 observations have available_at <= Feb 1 → all included (latest per key)
        assert result.row_count >= 1


class TestHashStability:
    def test_panel_id_deterministic(self, tmp_path: Path) -> None:
        silver = _silver_rows(["QQQ"], 3)
        b1 = PitPanelBuilder(silver_df=silver)
        b2 = PitPanelBuilder(silver_df=silver)
        r1 = b1.build(
            datetime(2024, 1, 15, 18, 0, tzinfo=UTC), ["QQQ"], output_dir=tmp_path
        )
        r2 = b2.build(
            datetime(2024, 1, 15, 18, 0, tzinfo=UTC), ["QQQ"], output_dir=tmp_path
        )
        assert r1.panel_id == r2.panel_id
        assert r1.panel_sha256 == r2.panel_sha256


class TestQualityScore:
    def test_all_valid_yields_good(self, tmp_path: Path) -> None:
        silver = _silver_rows(["QQQ"], 3)
        for i in range(3):
            silver = silver.with_columns(
                pl.when(pl.col("observation_id") == f"obs_0_{i}")
                .then(pl.lit("VALID"))
                .otherwise(pl.col("quality_status"))
                .alias("quality_status")
            )
        builder = PitPanelBuilder(silver_df=silver)
        result = builder.build(
            datetime(2024, 2, 1, 12, 0, tzinfo=UTC), ["QQQ"], output_dir=tmp_path
        )
        assert result.quality_status == "GOOD"

    def test_empty_panel_rejected(self, tmp_path: Path) -> None:
        builder = PitPanelBuilder(silver_df=pl.DataFrame())
        result = builder.build(
            datetime(2024, 1, 15, 18, 0, tzinfo=UTC), ["QQQ"], output_dir=tmp_path
        )
        assert result.quality_status == "REJECTED"
        assert result.quality_score == 0.0
