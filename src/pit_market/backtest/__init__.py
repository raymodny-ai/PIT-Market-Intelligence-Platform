"""Walk-forward backtest + research utilities (T-30)."""
from pit_market.backtest.engine import (
    FoldResult,
    WalkForwardConfig,
    WalkForwardResult,
    compute_ic,
    summarize,
    walk_forward,
    write_manifest,
)

__all__ = [
    "FoldResult",
    "WalkForwardConfig",
    "WalkForwardResult",
    "compute_ic",
    "summarize",
    "walk_forward",
    "write_manifest",
]
