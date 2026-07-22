"""Generate Phase 5 research notebooks (T-30).

Run with:
    python scripts/build_notebooks.py

Produces:
    notebooks/walk_forward_equity_v1.ipynb
    notebooks/factor_ic_attribution_v1.ipynb
    notebooks/bayesian_xgb_search_v1.ipynb
"""
from __future__ import annotations

import sys
from pathlib import Path

import nbformat as nbf
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "notebooks"


def walk_forward_notebook() -> nbf.NotebookNode:
    nb = new_notebook()
    nb.metadata["kernelspec"] = {
        "name": "python3",
        "display_name": "Python 3",
        "language": "python",
    }
    nb.metadata["language_info"] = {"name": "python", "version": "3.12"}
    nb.cells = [
        new_markdown_cell(
            "# Walk-Forward 回测 — 权益类因子 (T-30)\n"
            "\n"
            "目标:在 `train_size=252 / test_size=63` 滚动窗口下,对 2 个 P0 因子\n"
            "(`f1=流动性`, `f2=动量`) 做样本外回测,产出每个 fold 的 IC 与\n"
            "long-short spread,以及跨 fold 的均值 / IR。\n"
            "\n"
            "PIT 纪律:`embargo_days=1` 防止训练集与测试集日期重叠。\n"
            "\n"
            "上游数据:Silver 观测 → Feature Engine → `feature_cols` 列表。\n"
            "下游消费:回测 manifest 落 `data/reports/backtests/`,供 `report build` 引用。"
        ),
        new_code_cell(
            "import os, sys\n"
            "from pathlib import Path\n"
            "REPO = Path.cwd().resolve().parents[0] if Path.cwd().name == 'notebooks' else Path.cwd()\n"
            "sys.path.insert(0, str(REPO / 'src'))\n"
            "import pandas as pd, numpy as np\n"
            "from pit_market.backtest import (\n"
            "    WalkForwardConfig, walk_forward, write_manifest, summarize\n"
            ")"
        ),
        new_code_cell(
            "# 1. 加载 Silver + Features (此处用合成数据演示,真实场景从 DuckDB 读)\n"
            "rng = np.random.default_rng(42)\n"
            "dates = pd.bdate_range('2022-01-03', periods=1200)\n"
            "features = pd.DataFrame({\n"
            "    'liquidity_z': rng.normal(0, 1, 1200),\n"
            "    'momentum_20': rng.normal(0, 1, 1200),\n"
            "}, index=dates)\n"
            "target = 0.02 * features['liquidity_z'] + 0.01 * features['momentum_20'] + 0.005 * rng.normal(0, 1, 1200)\n"
            "returns = pd.DataFrame({'fwd_return_1d': target}, index=dates)"
        ),
        new_code_cell(
            "# 2. 配置 walk-forward 参数\n"
            "cfg = WalkForwardConfig(\n"
            "    train_size=252, test_size=63, step=63,\n"
            "    feature_cols=('liquidity_z', 'momentum_20'),\n"
            "    min_train=126, embargo_days=1,\n"
            ")"
        ),
        new_code_cell(
            "# 3. 跑回测\n"
            "result = walk_forward(features, returns, cfg)\n"
            "print(f'folds={len(result.folds)}  ic_mean={result.aggregate_ic():.4f}')\n"
            "for fold in result.folds[:3]:\n"
            "    print(fold)"
        ),
        new_code_cell(
            "# 4. 写 manifest 到 data/reports/backtests/\n"
            "out_dir = REPO / 'data' / 'reports' / 'backtests'\n"
            "out_dir.mkdir(parents=True, exist_ok=True)\n"
            "summary_path = write_manifest(result, out_dir)\n"
            "print('manifest →', summary_path)"
        ),
        new_code_cell(
            "# 5. 汇总统计\n"
            "summary = summarize(result)\n"
            "summary"
        ),
    ]
    return nb


def factor_ic_notebook() -> nbf.NotebookNode:
    nb = new_notebook()
    nb.metadata["kernelspec"] = {
        "name": "python3",
        "display_name": "Python 3",
        "language": "python",
    }
    nb.metadata["language_info"] = {"name": "python", "version": "3.12"}
    nb.cells = [
        new_markdown_cell(
            "# 因子 IC 归因 (T-30)\n"
            "\n"
            "对每个 fold 计算每个因子的边际 IC,产出 Pareto 表格,识别\n"
            "在样本外持续有效的因子子集。"
        ),
        new_code_cell(
            "import sys\n"
            "from pathlib import Path\n"
            "REPO = Path.cwd().resolve().parents[0] if Path.cwd().name == 'notebooks' else Path.cwd()\n"
            "sys.path.insert(0, str(REPO / 'src'))\n"
            "import pandas as pd, numpy as np\n"
            "from pit_market.backtest import compute_ic"
        ),
        new_code_cell(
            "rng = np.random.default_rng(0)\n"
            "dates = pd.bdate_range('2022-01-03', periods=600)\n"
            "factors = pd.DataFrame({\n"
            "    'a': rng.normal(0, 1, 600),\n"
            "    'b': rng.normal(0, 1, 600),\n"
            "    'c': rng.normal(0, 1, 600),\n"
            "}, index=dates)\n"
            "returns = 0.03 * factors['a'] + 0.01 * factors['b'] + 0.005 * rng.normal(0, 1, 600)\n"
            "returns = pd.Series(returns, index=dates, name='r')"
        ),
        new_code_cell(
            "ic_table = pd.DataFrame({\n"
            "    col: [compute_ic(factors[col], returns) for _ in range(1)]\n"
            "    for col in factors.columns\n"
            "}, index=['ic']).T\n"
            "ic_table"
        ),
    ]
    return nb


def bayesian_xgb_notebook() -> nbf.NotebookNode:
    nb = new_notebook()
    nb.metadata["kernelspec"] = {
        "name": "python3",
        "display_name": "Python 3",
        "language": "python",
    }
    nb.metadata["language_info"] = {"name": "python", "version": "3.12"}
    nb.cells = [
        new_markdown_cell(
            "# XGBoost 贝叶斯超参搜索 (T-30)\n"
            "\n"
            "用 Optuna 在 walk-forward 的 OOS 段上最大化 IC 的均值。\n"
            "搜索空间:`max_depth ∈ [3, 8]`, `learning_rate ∈ [0.01, 0.3]` (log),\n"
            "`n_estimators ∈ [50, 300]`, `subsample ∈ [0.6, 1.0]`。\n"
            "\n"
            "⚠️ 完整运行需要 `pip install -e .[research]`(xgboost + optuna)。"
        ),
        new_code_cell(
            "import sys\n"
            "from pathlib import Path\n"
            "REPO = Path.cwd().resolve().parents[0] if Path.cwd().name == 'notebooks' else Path.cwd()\n"
            "sys.path.insert(0, str(REPO / 'src'))\n"
            "import pandas as pd, numpy as np\n"
            "try:\n"
            "    import optuna\n"
            "    import xgboost as xgb\n"
            "except ImportError as e:\n"
            "    raise SystemExit('pip install -e .[research]') from e"
        ),
        new_code_cell(
            "rng = np.random.default_rng(7)\n"
            "dates = pd.bdate_range('2022-01-03', periods=800)\n"
            "X = pd.DataFrame({\n"
            "    'f1': rng.normal(0, 1, 800),\n"
            "    'f2': rng.normal(0, 1, 800),\n"
            "    'f3': rng.normal(0, 1, 800),\n"
            "}, index=dates)\n"
            "y = 0.04 * X['f1'] + 0.02 * X['f2'] + 0.005 * rng.normal(0, 1, 800)"
        ),
        new_code_cell(
            "def objective(trial):\n"
            "    params = {\n"
            "        'max_depth': trial.suggest_int('max_depth', 3, 8),\n"
            "        'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),\n"
            "        'n_estimators': trial.suggest_int('n_estimators', 50, 300),\n"
            "        'subsample': trial.suggest_float('subsample', 0.6, 1.0),\n"
            "    }\n"
            "    from pit_market.backtest import WalkForwardConfig, walk_forward\n"
            "    returns = pd.DataFrame({'fwd_return_1d': y}, index=dates)\n"
            "    cfg = WalkForwardConfig(\n"
            "        train_size=252, test_size=63, step=63,\n"
            "        feature_cols=('f1', 'f2', 'f3'),\n"
            "        min_train=126,\n"
            "        model_factory=lambda: xgb.XGBRegressor(**params, verbosity=0),\n"
            "    )\n"
            "    res = walk_forward(X, returns, cfg)\n"
            "    return res.aggregate_ic()"
        ),
        new_code_cell(
            "study = optuna.create_study(direction='maximize')\n"
            "study.optimize(objective, n_trials=10, show_progress_bar=False)\n"
            "study.best_params"
        ),
    ]
    return nb


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    notebooks = {
        "walk_forward_equity_v1.ipynb": walk_forward_notebook(),
        "factor_ic_attribution_v1.ipynb": factor_ic_notebook(),
        "bayesian_xgb_search_v1.ipynb": bayesian_xgb_notebook(),
    }
    for name, nb in notebooks.items():
        path = OUT / name
        nbf.write(nb, str(path))
        print(f"wrote {path}")
    print(f"OK — {len(notebooks)} notebooks under {OUT}")


if __name__ == "__main__":
    sys.exit(main() or 0)
