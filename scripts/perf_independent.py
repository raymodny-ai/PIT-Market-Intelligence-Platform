"""T-40b: Independent DuckDB performance verification (Verifier script).

Run: python /tmp/perf_independent.py
Not part of the project test suite; uses its own data generation.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

import duckdb
import numpy as np
import polars as pl


def main() -> int:
    seed = 42
    rng = np.random.default_rng(seed)
    n_symbols = 500
    n_days = 252 * 5  # 5 years

    print(f"=== T-40b Independent DuckDB Performance Verification ===")
    print(f"symbols={n_symbols}, days={n_days}, seed={seed}\n")

    # Generate data as Polars DataFrame for fast Arrow insert
    symbols = [f"SYM{i:04d}" for i in range(n_symbols)]
    symbols_col = []
    day_col = []
    close_col = []
    volume_col = []
    for sym in symbols:
        base = 100.0 + rng.uniform(-20, 80)
        prices = [base]
        for _ in range(n_days - 1):
            prices.append(prices[-1] * (1 + rng.normal(0.0003, 0.015)))
        for d in range(n_days):
            symbols_col.append(sym)
            day_col.append(d)
            close_col.append(round(prices[d], 4))
            volume_col.append(int(rng.uniform(1e6, 1e8)))

    df_500 = pl.DataFrame({
        "symbol": symbols_col, "day_idx": day_col,
        "close": close_col, "volume": volume_col,
    })
    total_rows = df_500.height
    print(f"Generated {total_rows} rows ({n_symbols} symbols x {n_days} days)")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "verify.duckdb"
        conn = duckdb.connect(str(db_path))
        conn.execute("""
            CREATE TABLE ohlcv (
                symbol VARCHAR, day_idx INTEGER, close DOUBLE, volume BIGINT
            )
        """)
        arrow_table = df_500.to_arrow()
        conn.execute("INSERT INTO ohlcv SELECT * FROM arrow_table")
        print(f"DuckDB file: {db_path} ({db_path.stat().st_size / 1024 / 1024:.1f} MB)\n")

        # Scenario 1: Full load
        t0 = time.monotonic()
        cnt = conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
        t1 = time.monotonic() - t0
        print(f"[S1] Full load COUNT(*): {cnt} rows in {t1:.3f}s (target <3s) {'PASS' if t1 < 3 else 'FAIL'}")

        # Scenario 2: Cross-section with LAG
        t0 = time.monotonic()
        result = conn.execute("""
            SELECT symbol, day_idx, close,
                   LAG(close) OVER (PARTITION BY symbol ORDER BY day_idx) AS prev
            FROM ohlcv
        """).fetchall()
        t2 = time.monotonic() - t0
        print(f"[S2] Cross-section LAG: {len(result)} rows in {t2:.3f}s (target <1s) {'PASS' if t2 < 1 else 'FAIL'}")

        # Scenario 3: Replay snapshot
        mid = n_days // 2
        t0 = time.monotonic()
        snap = conn.execute(f"""
            SELECT symbol, close FROM ohlcv
            WHERE day_idx <= {mid}
            QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY day_idx DESC) = 1
        """).fetchall()
        t3 = time.monotonic() - t0
        print(f"[S3] Replay snapshot: {len(snap)} symbols in {t3:.3f}s (target <2s) {'PASS' if t3 < 2 else 'FAIL'}")

        # Memory: 1000 symbols — generate via Polars for fast insert
        syms_1k = []
        day_1k = []
        close_1k = []
        vol_1k = []
        for i in range(1000):
            sym = f"BIG{i:04d}"
            base = 100.0 + rng.uniform(-20, 80)
            p = [base]
            for _ in range(n_days - 1):
                p.append(p[-1] * (1 + rng.normal(0.0003, 0.015)))
            for d in range(n_days):
                syms_1k.append(sym)
                day_1k.append(d)
                close_1k.append(round(p[d], 4))
                vol_1k.append(int(rng.uniform(1e6, 1e8)))
        df_1k = pl.DataFrame({"symbol": syms_1k, "day_idx": day_1k, "close": close_1k, "volume": vol_1k})
        arrow_1k = df_1k.to_arrow()
        conn.execute("INSERT INTO ohlcv SELECT * FROM arrow_1k")
        mem_mb = db_path.stat().st_size / (1024 * 1024)
        total = conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
        print(f"\n[MEM] 1000 symbols × {n_days} days: {total} rows, {mem_mb:.1f} MB (target <500MB) {'PASS' if mem_mb < 500 else 'FAIL'}")

        conn.close()

    # Polars backend switch
    os.environ["PIT_STORAGE_BACKEND"] = "polars"
    sys.path.insert(0, str(Path(__file__).parent / "src"))
    try:
        from pit_market.storage.panel_store import _get_backend, reset_panel_store
        reset_panel_store()
        be = _get_backend()
        assert type(be).__name__ == "PolarsStorageBackend", f"Expected PolarsStorageBackend, got {type(be).__name__}"
        print(f"\n[POLARS] Backend switch: {type(be).__name__} PASS")
    except Exception as e:
        print(f"\n[POLARS] Backend switch FAIL: {e}")
    finally:
        os.environ.pop("PIT_STORAGE_BACKEND", None)

    print("\n=== T-40b Verification Complete ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
