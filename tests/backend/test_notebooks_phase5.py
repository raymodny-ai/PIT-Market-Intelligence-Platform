"""Phase 5 T-30 — research notebook scaffolding tests."""
from __future__ import annotations

from pathlib import Path

import nbformat
import pytest

REPO = Path(__file__).resolve().parents[2]
NOTEBOOKS = REPO / "notebooks"


@pytest.mark.parametrize("name", [
    "walk_forward_equity_v1.ipynb",
    "factor_ic_attribution_v1.ipynb",
    "bayesian_xgb_search_v1.ipynb",
])
def test_notebook_exists_and_parses(name: str) -> None:
    path = NOTEBOOKS / name
    assert path.is_file(), f"missing notebook: {path}"
    nb = nbformat.read(str(path), as_version=4)
    assert len(nb.cells) >= 4
    # at least one code cell must exist
    code_cells = [c for c in nb.cells if c.cell_type == "code"]
    assert len(code_cells) >= 3
    # at least one markdown cell
    md_cells = [c for c in nb.cells if c.cell_type == "markdown"]
    assert len(md_cells) >= 1


def test_walk_forward_notebook_uses_pit_market() -> None:
    nb = nbformat.read(str(NOTEBOOKS / "walk_forward_equity_v1.ipynb"), as_version=4)
    sources = "\n".join(c.source for c in nb.cells if c.cell_type == "code")
    assert "pit_market.backtest" in sources
    assert "embargo_days" in sources  # PIT discipline


def test_bayesian_notebook_mentions_optuna_and_xgboost() -> None:
    nb = nbformat.read(str(NOTEBOOKS / "bayesian_xgb_search_v1.ipynb"), as_version=4)
    sources = "\n".join(c.source for c in nb.cells if c.cell_type == "code")
    assert "optuna" in sources
    assert "xgb" in sources
    assert "create_study" in sources


def test_notebooks_have_kernel_spec() -> None:
    for name in (
        "walk_forward_equity_v1.ipynb",
        "factor_ic_attribution_v1.ipynb",
        "bayesian_xgb_search_v1.ipynb",
    ):
        nb = nbformat.read(str(NOTEBOOKS / name), as_version=4)
        assert "kernelspec" in nb.metadata
