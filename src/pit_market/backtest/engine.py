"""Walk-forward backtest engine (T-30).

PIT-aware by construction: each training window ends at ``train_end`` and
each test window starts at ``train_end + 1 trading day``. The engine
never peeks past ``train_end`` when building features, so leakage
matches the platform's PIT semantics.

Public surface:
    WalkForwardConfig: dataclass of all knobs
    WalkForwardResult: dataclass of folds + aggregates
    walk_forward(features, returns, cfg) -> WalkForwardResult
    compute_ic(factor, returns) -> float   # Pearson IC
    summarize(result) -> dict              # aggregate stats
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class WalkForwardConfig:
    train_size: int = 252      # ~1y daily bars
    test_size: int = 63        # ~3m OOS
    step: int = 63             # rolling by quarter
    min_train: int = 126
    feature_cols: tuple[str, ...] = ()
    target_col: str = "fwd_return_1d"
    embargo_days: int = 1      # T-12 leakage discipline
    model_factory: Callable[[], Any] | None = None  # returns a fresh model
    seed: int = 42


@dataclass
class FoldResult:
    fold_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    n_train: int
    n_test: int
    ic: float
    mean_pred: float
    std_pred: float
    long_short_spread: float  # mean(top decile) - mean(bottom decile)
    notes: str = ""


@dataclass
class WalkForwardResult:
    config: WalkForwardConfig
    folds: list[FoldResult] = field(default_factory=list)
    manifest_path: str = ""
    started_utc: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat()
    )

    def aggregate_ic(self) -> float:
        if not self.folds:
            return 0.0
        return float(np.mean([f.ic for f in self.folds]))

    def aggregate_long_short(self) -> float:
        if not self.folds:
            return 0.0
        return float(np.mean([f.long_short_spread for f in self.folds]))


def compute_ic(factor: pd.Series, returns: pd.Series) -> float:
    """Pearson IC (Information Coefficient) between factor and forward returns."""
    df = pd.concat([factor.rename("f"), returns.rename("r")], axis=1).dropna()
    if len(df) < 2:
        return 0.0
    return float(df["f"].corr(df["r"]))


def _safe_model_predict(
    x_train_df: pd.DataFrame,
    y_train: pd.Series,
    x_test_df: pd.DataFrame,
    cfg: WalkForwardConfig,
) -> tuple[pd.Series, str]:
    """Train the model on the training window and predict on the test window.

    If no ``model_factory`` is supplied, use a deterministic linear baseline
    (ordinary least squares on standardized features). This is the CI fallback
    so the backtest engine works in environments without xgboost.
    """
    if cfg.model_factory is None:
        # Deterministic linear baseline: y = sum(standardized_X) / sqrt(k)
        from sklearn.linear_model import LinearRegression
        model = LinearRegression()
        model.fit(x_train_df.values, y_train.values)
        preds = pd.Series(model.predict(x_test_df.values), index=x_test_df.index, name="pred")
        return preds, "linear_baseline"
    try:
        model = cfg.model_factory()
        model.fit(x_train_df, y_train)
        preds = pd.Series(model.predict(x_test_df), index=x_test_df.index, name="pred")
        return preds, type(model).__name__
    except Exception as e:  # pragma: no cover
        return pd.Series([0.0] * len(x_test_df), index=x_test_df.index, name="pred"), f"failed:{e}"


def walk_forward(
    features: pd.DataFrame,
    returns: pd.DataFrame,
    cfg: WalkForwardConfig,
) -> WalkForwardResult:
    """Run a walk-forward backtest.

    Args:
        features: DataFrame with at least ``cfg.feature_cols`` columns,
            indexed by date.
        returns: DataFrame with a ``cfg.target_col`` column, indexed by date.
        cfg: ``WalkForwardConfig``.

    Returns:
        WalkForwardResult with one FoldResult per fold.
    """
    if not cfg.feature_cols:
        raise ValueError("WalkForwardConfig.feature_cols is required")

    merged = features.join(returns[[cfg.target_col]], how="inner").dropna()
    if len(merged) < cfg.min_train + cfg.test_size:
        raise ValueError(
            f"Not enough data: have {len(merged)} rows, "
            f"need ≥ {cfg.min_train + cfg.test_size}"
        )

    result = WalkForwardResult(config=cfg)
    fold_id = 0
    i = 0
    while i + cfg.train_size + cfg.test_size <= len(merged):
        train = merged.iloc[i : i + cfg.train_size]
        test = merged.iloc[i + cfg.train_size + cfg.embargo_days :
                           i + cfg.train_size + cfg.embargo_days + cfg.test_size]
        if len(test) < cfg.test_size:
            break

        x_train_df = train[list(cfg.feature_cols)]
        y_train = train[cfg.target_col]
        x_test_df = test[list(cfg.feature_cols)]
        y_test = test[cfg.target_col]

        preds, model_name = _safe_model_predict(x_train_df, y_train, x_test_df, cfg)
        ic = compute_ic(preds, y_test)

        if len(preds) >= 10:
            q = pd.qcut(preds, 10, labels=False, duplicates="drop")
            top = y_test[q == q.max()].mean()
            bot = y_test[q == q.min()].mean()
            spread = float(top - bot) if pd.notna(top) and pd.notna(bot) else 0.0
        else:
            spread = 0.0

        result.folds.append(FoldResult(
            fold_id=fold_id,
            train_start=str(train.index[0].date()),
            train_end=str(train.index[-1].date()),
            test_start=str(test.index[0].date()),
            test_end=str(test.index[-1].date()),
            n_train=len(train),
            n_test=len(test),
            ic=ic,
            mean_pred=float(preds.mean()),
            std_pred=float(preds.std()),
            long_short_spread=spread,
            notes=model_name,
        ))
        fold_id += 1
        i += cfg.step
    return result


def summarize(result: WalkForwardResult) -> dict[str, Any]:
    """Aggregate fold-level stats into a single report dict."""
    if not result.folds:
        return {"folds": 0}
    ics = np.array([f.ic for f in result.folds])
    spreads = np.array([f.long_short_spread for f in result.folds])
    return {
        "folds": len(result.folds),
        "ic_mean": float(ics.mean()),
        "ic_std": float(ics.std()),
        "ic_ir": float(ics.mean() / ics.std()) if ics.std() > 0 else 0.0,
        "long_short_mean": float(spreads.mean()),
        "long_short_std": float(spreads.std()),
        "positive_ic_folds": int((ics > 0).sum()),
        "started_utc": result.started_utc,
        "config": asdict(result.config),
    }


def write_manifest(result: WalkForwardResult, output_dir: str | Path) -> Path:
    """Write fold-level manifest + summary JSON to ``output_dir``."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"wf-{datetime.now().strftime('%Y%m%dT%H%M%SZ')}"
    summary = summarize(result)
    summary["run_id"] = run_id
    folds_path = output_dir / f"{run_id}_folds.json"
    summary_path = output_dir / f"{run_id}_summary.json"
    folds_path.write_text(
        json.dumps([asdict(f) for f in result.folds], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary_path
