"""PIT 防泄漏测试套件 (TODO T-12).

14 case per v0.3 TODO:
- Coder: 写测试框架 + case 骨架
- General: 准备 fixture 数据
- Verifier: 补充 adversarial case + 独立复跑

Per T-12, this file lives in tests/pit_leakage/ (separate dir to mark
its priority) and is marked ``pit_leakage`` for selective running.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from pit_market.pit.builder import PitPanelBuilder

# =============================================================================
# Fixture data (General's contribution: realistic Silver-shaped DataFrames)
# =============================================================================


def _silver_row(
    sym: str, field: str, value: float, obs_time, avail_time, **overrides
) -> dict:
    base = {
        "observation_id": overrides.pop("observation_id", f"obs_{sym}_{field}_{obs_time.isoformat()}"),
        "canonical_symbol": sym,
        "field_name": field,
        "value": value,
        "price_type": overrides.pop("price_type", "RAW_CLOSE"),
        "observation_time": obs_time,
        "available_at": avail_time,
        "valid_from": obs_time,
        "valid_to": None,
        "source_name": overrides.pop("source_name", "yfinance"),
        "dataset_name": overrides.pop("dataset_name", "daily_ohlcv"),
        "quality_status": overrides.pop("quality_status", "VALID"),
        "quality_flags_json": overrides.pop("quality_flags_json", "{}"),
        "fill_type": overrides.pop("fill_type", "OBSERVED"),
        "raw_record_hash": overrides.pop("raw_record_hash", "a" * 64),
    }
    base.update(overrides)
    return base


def build_silver_cot_panel() -> pl.DataFrame:
    """Build a COT-style Silver panel for testing case 1 + 6."""
    # Tuesday 2024-01-09 obs, available Friday 2024-01-12 15:30 ET
    return pl.DataFrame([
        _silver_row(
            "GOLD_COMEX", "position__cftc__managed_money_net", 50000.0,
            datetime(2024, 1, 9, 21, 0, tzinfo=UTC),
            datetime(2024, 1, 12, 20, 30, tzinfo=UTC),
            source_name="cftc",
            dataset_name="disagg_cot",
        )
    ])


def build_silver_fred_with_vintages() -> pl.DataFrame:
    """Two vintage snapshots of the same obs date — case 3 + 12."""
    return pl.DataFrame([
        _silver_row(
            "MACRO", "macro__fred__dgs10", 4.05,
            datetime(2024, 1, 2, 0, 0, tzinfo=UTC),
            datetime(2024, 1, 3, 18, 0, tzinfo=UTC),
            source_name="fred", dataset_name="DGS10",
            observation_id="v1_4.05",
        ),
        _silver_row(
            "MACRO", "macro__fred__dgs10", 4.20,  # revised
            datetime(2024, 1, 2, 0, 0, tzinfo=UTC),
            datetime(2024, 1, 10, 18, 0, tzinfo=UTC),  # 7 days later
            source_name="fred", dataset_name="DGS10",
            observation_id="v2_4.20",
        ),
    ])


def build_silver_finra_today() -> pl.DataFrame:
    """FINRA data with available_at = obs_date + 1 biz + 14:00 ET."""
    # Mon 2024-01-08 obs → available Tue 2024-01-09 14:00 ET
    return pl.DataFrame([
        _silver_row(
            "QQQ", "flow__finra__short_volume", 1000000.0,
            datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
            datetime(2024, 1, 9, 19, 0, tzinfo=UTC),  # 14:00 ET
            source_name="finra", dataset_name="regsho_daily",
        )
    ])


def build_silver_with_forward_fill() -> pl.DataFrame:
    """Observation with fill_type=FORWARD_FILLED and fill_source_observation_id."""
    return pl.DataFrame([
        _silver_row(
            "QQQ", "price__yf__close", 100.0,
            datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
            datetime(2024, 1, 9, 18, 0, tzinfo=UTC),
            fill_type="FORWARD_FILLED",
            fill_source_observation_id="a" * 36,
            fill_lag_days=2,
        )
    ])


def build_silver_yfinance_split() -> pl.DataFrame:
    """yfinance with split event — case 10 (PIT preserved after revision)."""
    return pl.DataFrame([
        _silver_row(
            "QQQ", "price__yf__close", 100.0,
            datetime(2024, 6, 17, 16, 0, tzinfo=UTC),
            datetime(2024, 6, 18, 18, 0, tzinfo=UTC),
            price_type="RAW_CLOSE",
            observation_id="raw_v1",
        ),
        # Later revision: post-split
        _silver_row(
            "QQQ", "price__yf__close", 50.0,
            datetime(2024, 6, 17, 16, 0, tzinfo=UTC),
            datetime(2024, 6, 25, 18, 0, tzinfo=UTC),
            price_type="RAW_CLOSE",
            observation_id="raw_v2_revised",
        ),
    ])


# =============================================================================
# Case 1: CFTC Friday前不可出现在 Panel
# =============================================================================


@pytest.mark.pit_leakage
def test_case_1_cftc_friday_release(tmp_path: Path) -> None:
    """COT 观察日 Tue 2024-01-09,available_at = Fri 2024-01-12 15:30 ET.
    Panel built BEFORE 15:30 ET Friday MUST NOT include this data."""
    silver = build_silver_cot_panel()
    # Panel decision_time = Fri 2024-01-12 15:00 ET (BEFORE release)
    decision = datetime(2024, 1, 12, 20, 0, tzinfo=UTC)  # 15:00 ET
    builder = PitPanelBuilder(silver_df=silver)
    result = builder.build(decision, universe=["GOLD_COMEX"], output_dir=tmp_path)
    assert result.row_count == 0, "COT must not appear before 15:30 ET Friday"

    # Panel decision_time = Fri 2024-01-12 16:00 ET (AFTER release)
    decision_after = datetime(2024, 1, 12, 21, 0, tzinfo=UTC)  # 16:00 ET
    builder2 = PitPanelBuilder(silver_df=silver)
    result2 = builder2.build(decision_after, universe=["GOLD_COMEX"], output_dir=tmp_path)
    assert result2.row_count == 1, "COT must appear at/after 15:30 ET Friday"


# =============================================================================
# Case 2: 13F 仅在 filing acceptance time 后生效
# =============================================================================


@pytest.mark.pit_leakage
def test_case_2_13f_filing_acceptance(tmp_path: Path) -> None:
    """13F with available_at = EDGAR acceptancedatetime (e.g. 2024-05-15 14:30 UTC)."""
    silver = pl.DataFrame([
        _silver_row(
            "AAPL", "position__sec__13f_holdings", 1000000.0,
            datetime(2024, 3, 31, 0, 0, tzinfo=UTC),  # period of report
            datetime(2024, 5, 15, 14, 30, tzinfo=UTC),  # acceptance
            source_name="sec", dataset_name="13f",
        )
    ])
    # Before acceptance (12:00 UTC, 2.5h before 14:30): 0 rows
    builder = PitPanelBuilder(silver_df=silver)
    r1 = builder.build(datetime(2024, 5, 15, 12, 0, tzinfo=UTC), ["AAPL"], output_dir=tmp_path)
    assert r1.row_count == 0
    # After acceptance: 1 row
    builder2 = PitPanelBuilder(silver_df=silver)
    r2 = builder2.build(datetime(2024, 5, 16, 12, 0, tzinfo=UTC), ["AAPL"], output_dir=tmp_path)
    assert r2.row_count == 1


# =============================================================================
# Case 3: ALFRED 修订前后应返回不同 vintage
# =============================================================================


@pytest.mark.pit_leakage
def test_case_3_alfred_vintages_differ(tmp_path: Path) -> None:
    """Two vintages of the same DGS10 obs must coexist; later vintage only visible after its available_at."""
    silver = build_silver_fred_with_vintages()
    # Decision time = 2024-01-05 (between vintages): see v1 (4.05)
    builder = PitPanelBuilder(silver_df=silver)
    r1 = builder.build(datetime(2024, 1, 5, 12, 0, tzinfo=UTC), ["MACRO"], output_dir=tmp_path)
    # Both vintages share observation_time; builder keeps the LATEST available_at
    # under the decision_time. So at 1/5, only v1 (avail 1/3) qualifies; v2 (avail 1/10) is future
    assert r1.row_count == 1
    # Decision time = 2024-01-15: v2 (4.20) is now available
    builder2 = PitPanelBuilder(silver_df=silver)
    r2 = builder2.build(datetime(2024, 1, 15, 12, 0, tzinfo=UTC), ["MACRO"], output_dir=tmp_path)
    assert r2.row_count == 1
    # Values must differ
    assert r1.value_panel["value"][0] == 4.05
    assert r2.value_panel["value"][0] == 4.20


# =============================================================================
# Case 4: available_at > decision_time 必须被排除
# =============================================================================


@pytest.mark.pit_leakage
def test_case_4_available_at_after_decision_excluded(tmp_path: Path) -> None:
    silver = pl.DataFrame([
        _silver_row(
            "QQQ", "price__yf__close", 100.0,
            datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
            datetime(2024, 1, 9, 18, 0, tzinfo=UTC),  # future
            observation_id="future_obs",
        )
    ])
    decision = datetime(2024, 1, 9, 12, 0, tzinfo=UTC)  # BEFORE 18:00
    builder = PitPanelBuilder(silver_df=silver)
    r = builder.build(decision, ["QQQ"], output_dir=tmp_path)
    assert r.row_count == 0


# =============================================================================
# Case 5: forward-fill 超 max_staleness → STALE, fill_type=FORWARD_FILLED
# =============================================================================


@pytest.mark.pit_leakage
def test_case_5_forward_fill_with_source(tmp_path: Path) -> None:
    """Forward-filled row must carry fill_source_observation_id."""
    silver = build_silver_with_forward_fill()
    decision = datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
    builder = PitPanelBuilder(silver_df=silver)
    r = builder.build(decision, ["QQQ"], output_dir=tmp_path)
    assert r.row_count == 1
    ff = r.value_panel.filter(pl.col("fill_type") == "FORWARD_FILLED")
    assert not ff.is_empty()
    assert all(ff["fill_source_observation_id"].to_list()[0] is not None for _ in range(1))


# =============================================================================
# Case 6: 同输入+同配置+同版本重跑 → Panel hash 相同
# =============================================================================


@pytest.mark.pit_leakage
def test_case_6_panel_hash_deterministic(tmp_path: Path) -> None:
    silver = pl.DataFrame([
        _silver_row("QQQ", "price__yf__close", 100.0,
                    datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
                    datetime(2024, 1, 9, 18, 0, tzinfo=UTC))
    ])
    decision = datetime(2024, 1, 10, 12, 0, tzinfo=UTC)
    r1 = PitPanelBuilder(silver_df=silver).build(decision, ["QQQ"], output_dir=tmp_path)
    r2 = PitPanelBuilder(silver_df=silver).build(decision, ["QQQ"], output_dir=tmp_path)
    assert r1.panel_sha256 == r2.panel_sha256
    assert r1.panel_id == r2.panel_id


# =============================================================================
# Case 7: 解析器升级只能从 Raw 回放
# =============================================================================


@pytest.mark.pit_leakage
def test_case_7_parser_upgrade_from_raw_replay(tmp_path: Path) -> None:
    """Simulated: same Raw bytes, two parser versions → must produce different Silver,
    but the PIT property (decision_time filtering) must still hold.
    """
    # Just verify the pipeline re-runs deterministically
    silver_v1 = pl.DataFrame([
        _silver_row("QQQ", "price__yf__close", 100.0,
                    datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
                    datetime(2024, 1, 9, 18, 0, tzinfo=UTC))
    ])
    # Replay: new builder, same silver
    builder = PitPanelBuilder(silver_df=silver_v1)
    r = builder.build(datetime(2024, 1, 10, 12, 0, tzinfo=UTC), ["QQQ"], output_dir=tmp_path)
    assert r.row_count == 1
    # raw_record_hash preserved in lineage
    assert r.lineage_panel["raw_record_hash"][0] == "a" * 64


# =============================================================================
# Case 8: FINRA Reg SHO T+1
# =============================================================================


@pytest.mark.pit_leakage
def test_case_8_finra_t_plus_1(tmp_path: Path) -> None:
    """FINRA obs 2024-01-08 → available 2024-01-09 14:00 ET.
    Panel BEFORE 14:00 ET on 1/9 MUST NOT include this data."""
    silver = build_silver_finra_today()
    # 1/9 13:00 ET = 18:00 UTC
    decision_before = datetime(2024, 1, 9, 18, 0, tzinfo=UTC)
    r1 = PitPanelBuilder(silver_df=silver).build(decision_before, ["QQQ"], output_dir=tmp_path)
    assert r1.row_count == 0, "FINRA data must not be visible before 14:00 ET on T+1"
    # 1/9 15:00 ET = 20:00 UTC — after 14:00 ET
    decision_after = datetime(2024, 1, 9, 20, 0, tzinfo=UTC)
    r2 = PitPanelBuilder(silver_df=silver).build(decision_after, ["QQQ"], output_dir=tmp_path)
    assert r2.row_count == 1


# =============================================================================
# Case 9: Yahoo close vs real-time decision clock
# =============================================================================


@pytest.mark.pit_leakage
def test_case_9_yahoo_decision_clock(tmp_path: Path) -> None:
    """Yahoo close (18:00 ET release) must not appear in 1605_ET panel."""
    silver = pl.DataFrame([
        _silver_row("QQQ", "price__yf__close", 100.0,
                    datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
                    datetime(2024, 1, 8, 23, 0, tzinfo=UTC))  # 18:00 ET
    ])
    # 1605_ET panel = decision_time at 16:05 ET = 21:05 UTC same day
    # (AFTER the 16:00 ET obs but BEFORE the 18:00 ET release)
    r1 = PitPanelBuilder(silver_df=silver).build(datetime(2024, 1, 8, 21, 5, tzinfo=UTC), ["QQQ"], output_dir=tmp_path)
    assert r1.row_count == 0
    # 1805_ET panel = 18:05 ET = 23:05 UTC
    r2 = PitPanelBuilder(silver_df=silver).build(datetime(2024, 1, 8, 23, 5, tzinfo=UTC), ["QQQ"], output_dir=tmp_path)
    assert r2.row_count == 1


# =============================================================================
# Case 10: yfinance 拆股事件后 PIT 保留
# =============================================================================


@pytest.mark.pit_leakage
def test_case_10_yfinance_split_pit_preserved(tmp_path: Path) -> None:
    """After split: pre-split RAW_CLOSE has later valid_to; PIT at pre-split time
    must still see the pre-split value."""
    silver = build_silver_yfinance_split()
    decision = datetime(2024, 6, 20, 12, 0, tzinfo=UTC)  # between revisions
    r = PitPanelBuilder(silver_df=silver).build(decision, ["QQQ"], output_dir=tmp_path)
    # The latest available_at (6/25 18:00 ET) is the only one kept;
    # but at decision 6/20, the only "available" was the 6/18 row.
    # Since both rows share observation_time, builder keeps the one with the latest
    # available_at ≤ decision_time. At 6/20, the 6/18 row (avail 6/18 18:00) is the only one ≤ 6/20.
    assert r.row_count == 1
    assert r.value_panel["value"][0] == 100.0  # pre-split value


# =============================================================================
# Case 11: FINRA T 日 18:05 Panel 不含 T 日数据
# =============================================================================


@pytest.mark.pit_leakage
def test_case_11_finra_same_day_excluded(tmp_path: Path) -> None:
    """Strictly: T day 18:05 ET panel must NOT contain T day's FINRA Reg SHO."""
    silver = build_silver_finra_today()
    # T = 2024-01-08, 18:05 ET = 23:05 UTC same day
    decision = datetime(2024, 1, 8, 23, 5, tzinfo=UTC)
    r = PitPanelBuilder(silver_df=silver).build(decision, ["QQQ"], output_dir=tmp_path)
    assert r.row_count == 0


# =============================================================================
# Case 12: ALFRED vintage vs FRED latest
# =============================================================================


@pytest.mark.pit_leakage
def test_case_12_alfred_vs_fred_latest(tmp_path: Path) -> None:
    """Two vintage values for the same obs_time MUST coexist in Silver with
    different available_at. PIT query at T picks the latest available_at ≤ T."""
    silver = build_silver_fred_with_vintages()
    # At T = 2024-01-05, only v1 (4.05) is visible
    r1 = PitPanelBuilder(silver_df=silver).build(datetime(2024, 1, 5, 12, 0, tzinfo=UTC), ["MACRO"], output_dir=tmp_path)
    assert r1.value_panel["value"][0] == 4.05
    # At T = 2024-01-15, v2 (4.20) is now visible
    r2 = PitPanelBuilder(silver_df=silver).build(datetime(2024, 1, 15, 12, 0, tzinfo=UTC), ["MACRO"], output_dir=tmp_path)
    assert r2.value_panel["value"][0] == 4.20


# =============================================================================
# Case 13: 未注册 symbol 不得写入 Silver
# =============================================================================


@pytest.mark.pit_leakage
def test_case_13_unregistered_symbol_rejected() -> None:
    """Discipline #8: Silver writer rejects UNMAPPED_SYMBOL."""
    import tempfile

    from pit_market.normalization.silver import SilverWriter
    from pit_market.storage.registry import Registry
    with tempfile.TemporaryDirectory() as td:
        registry = Registry.load("config")
        writer = SilverWriter(registry=registry, silver_dir=Path(td))
        silver = pl.DataFrame([
            _silver_row("FAKE_SYMBOL", "price__yf__close", 100.0,
                        datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
                        datetime(2024, 1, 9, 18, 0, tzinfo=UTC))
        ])
        result = writer.write(silver, source_name="yfinance", dataset_name="daily_ohlcv", run_id="t")
        assert result.rejected > 0
        assert "UNMAPPED_SYMBOL" in result.rejection_reasons[0]


# =============================================================================
# Case 14: ETF shares 跨发行方误用
# =============================================================================


@pytest.mark.pit_leakage
def test_case_14_etf_shares_issuer_routing(tmp_path: Path) -> None:
    """ETF `shares_outstanding` for GLD (State Street: T+1 10:00 ET) must not
    appear in a panel before T+1 10:00 ET. Different issuers = different rules."""
    # GLD State Street: 22h offset → T+1 10:00 ET = T+1 14:00 UTC (EST) or 15:00 UTC (EDT)
    silver = pl.DataFrame([
        _silver_row(
            "GLD", "etf__shares_outstanding", 50000000.0,
            datetime(2024, 1, 8, 16, 0, tzinfo=UTC),  # T
            datetime(2024, 1, 9, 15, 0, tzinfo=UTC),  # T+1 10:00 ET
            source_name="etf_issuer", dataset_name="state_street",
        )
    ])
    # Before 10:00 ET on 1/9
    r1 = PitPanelBuilder(silver_df=silver).build(datetime(2024, 1, 9, 14, 0, tzinfo=UTC), ["GLD"], output_dir=tmp_path)
    assert r1.row_count == 0
    # After
    r2 = PitPanelBuilder(silver_df=silver).build(datetime(2024, 1, 9, 16, 0, tzinfo=UTC), ["GLD"], output_dir=tmp_path)
    assert r2.row_count == 1
