"""Phase 5 T-30 — walk-forward backtest engine tests."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pit_market.backtest import (
    WalkForwardConfig,
    compute_ic,
    summarize,
    walk_forward,
    write_manifest,
)


def _synthetic_features(n: int = 600, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build a synthetic factor / returns pair with a known signal.

    The factor is partially predictive: corr(factor, future_return) ≈ 0.4.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n)
    f1 = rng.normal(0, 1, n)
    f2 = rng.normal(0, 1, n)
    noise = rng.normal(0, 1, n)
    target = 0.02 * f1 + 0.01 * f2 + 0.005 * noise
    features = pd.DataFrame({"f1": f1, "f2": f2}, index=dates)
    returns = pd.DataFrame({"fwd_return_1d": target}, index=dates)
    return features, returns


def test_compute_ic_returns_float() -> None:
    f, r = _synthetic_features()
    ic = compute_ic(f["f1"], r["fwd_return_1d"])
    assert isinstance(ic, float)
    # signal is real → |IC| > 0.1
    assert abs(ic) > 0.1


def test_compute_ic_handles_short_series() -> None:
    f, r = _synthetic_features(5)
    # 5 rows is enough for Pearson IC (need ≥2 non-null pairs)
    ic = compute_ic(f["f1"], r["fwd_return_1d"])
    assert isinstance(ic, float)


def test_compute_ic_handles_empty_series() -> None:
    empty_f = pd.Series(dtype=float)
    empty_r = pd.Series(dtype=float)
    assert compute_ic(empty_f, empty_r) == 0.0


def test_walk_forward_requires_feature_cols() -> None:
    f, r = _synthetic_features()
    cfg = WalkForwardConfig(train_size=100, test_size=20, step=20)
    with pytest.raises(ValueError, match="feature_cols"):
        walk_forward(f, r, cfg)


def test_walk_forward_produces_folds() -> None:
    f, r = _synthetic_features(800)
    cfg = WalkForwardConfig(
        train_size=252, test_size=63, step=63,
        feature_cols=("f1", "f2"), min_train=126,
    )
    result = walk_forward(f, r, cfg)
    assert len(result.folds) >= 2
    # Each fold must have non-empty train and test
    for fold in result.folds:
        assert fold.n_train == 252
        assert fold.n_test == 63
        assert fold.ic != 0 or fold.long_short_spread != 0


def test_walk_forward_no_peekage() -> None:
    """The test window must always be strictly after the train window."""
    f, r = _synthetic_features(800)
    cfg = WalkForwardConfig(
        train_size=200, test_size=30, step=30,
        feature_cols=("f1",), min_train=120,
    )
    result = walk_forward(f, r, cfg)
    for fold in result.folds:
        assert fold.train_end < fold.test_start


def test_walk_forward_embargo_respected() -> None:
    """At least ``embargo_days`` must separate train and test windows."""
    f, r = _synthetic_features(800)
    cfg = WalkForwardConfig(
        train_size=200, test_size=30, step=30,
        feature_cols=("f1",), min_train=120, embargo_days=5,
    )
    result = walk_forward(f, r, cfg)
    for fold in result.folds:
        train_end = pd.Timestamp(fold.train_end)
        test_start = pd.Timestamp(fold.test_start)
        # bdate_range → at least 5 business days
        bdays = len(pd.bdate_range(train_end, test_start)) - 1
        assert bdays >= 5


def test_walk_forward_rejects_too_small_data() -> None:
    f, r = _synthetic_features(50)
    cfg = WalkForwardConfig(
        train_size=200, test_size=30, step=30,
        feature_cols=("f1",), min_train=120,
    )
    with pytest.raises(ValueError, match="Not enough data"):
        walk_forward(f, r, cfg)


def test_walk_forward_with_xgboost(tmp_path: Path) -> None:
    """If xgboost is installed, the engine can use it; falls back to linear."""
    pytest.importorskip("xgboost")
    f, r = _synthetic_features(800)
    import xgboost as xgb
    cfg = WalkForwardConfig(
        train_size=252, test_size=63, step=63,
        feature_cols=("f1", "f2"),
        model_factory=lambda: xgb.XGBRegressor(
            n_estimators=50, max_depth=3, learning_rate=0.05, verbosity=0,
        ),
    )
    result = walk_forward(f, r, cfg)
    assert len(result.folds) >= 1
    assert result.folds[0].notes.startswith("XGB")


def test_summarize_empty_result() -> None:
    cfg = WalkForwardConfig(feature_cols=("f1",))
    # synthesise empty result via dataclass
    from pit_market.backtest import WalkForwardResult
    empty = WalkForwardResult(config=cfg)
    s = summarize(empty)
    assert s == {"folds": 0}


def test_summarize_real_run() -> None:
    f, r = _synthetic_features(800)
    cfg = WalkForwardConfig(
        train_size=252, test_size=63, step=63, feature_cols=("f1", "f2"),
    )
    result = walk_forward(f, r, cfg)
    s = summarize(result)
    assert s["folds"] >= 1
    assert "ic_mean" in s
    assert "long_short_mean" in s
    assert "started_utc" in s


def test_write_manifest_creates_files(tmp_path: Path) -> None:
    f, r = _synthetic_features(800)
    cfg = WalkForwardConfig(
        train_size=200, test_size=30, step=30, feature_cols=("f1",),
    )
    result = walk_forward(f, r, cfg)
    summary_path = write_manifest(result, tmp_path)
    assert summary_path.exists()
    files = list(tmp_path.glob("wf-*"))
    assert len(files) == 2  # folds + summary
    # round-trip
    import json
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert "folds" in summary
    assert "ic_mean" in summary
    assert "run_id" in summary


def test_aggregate_ic_returns_zero_for_empty() -> None:
    from pit_market.backtest import WalkForwardResult
    cfg = WalkForwardConfig(feature_cols=("f1",))
    res = WalkForwardResult(config=cfg)
    assert res.aggregate_ic() == 0.0
    assert res.aggregate_long_short() == 0.0
