"""Tests for T-37 DuckDB storage layer.

Covers:
- StorageBackend Protocol compliance (DuckDB + Polars)
- 4-table DDL migration
- CRUD operations (upsert, query, list, delete)
- PIT_DUCKDB_PATH fallback
- Concurrent write stress test (2 threads simultaneous upsert)
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_duckdb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each test gets its own DuckDB file to avoid cross-test interference."""
    db_path = str(tmp_path / "test.duckdb")
    monkeypatch.setenv("PIT_DUCKDB_PATH", db_path)
    # Reset singleton before each test
    from pit_market.storage import duckdb_engine
    duckdb_engine.close()
    yield
    duckdb_engine.close()


@pytest.fixture()
def duckdb_backend():
    from pit_market.storage.duckdb_backend import DuckDBStorageBackend
    return DuckDBStorageBackend()


@pytest.fixture()
def polars_backend():
    from pit_market.storage.polars_backend import PolarsStorageBackend
    return PolarsStorageBackend()


# ---------------------------------------------------------------------------
# DDL / migration tests
# ---------------------------------------------------------------------------


class TestMigrations:
    def test_tables_created(self):
        """4 tables + _migrations meta-table exist after first connect."""
        from pit_market.storage.duckdb_engine import get_connection
        conn = get_connection()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        for expected in ("panels", "data_registry", "replay_snapshots", "backtest_runs", "_migrations"):
            assert expected in tables, f"missing table: {expected}"

    def test_migration_idempotent(self):
        """Re-running migrations does not fail."""
        from pit_market.storage.duckdb_engine import get_connection
        conn = get_connection()
        # Force re-run by deleting migration record
        conn.execute("DELETE FROM _migrations WHERE migration_id = '001_init_schema'")
        # Re-trigger
        from pit_market.storage import duckdb_engine
        duckdb_engine.close()
        conn2 = get_connection()
        count = conn2.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]
        assert count >= 1


# ---------------------------------------------------------------------------
# DuckDB StorageBackend CRUD
# ---------------------------------------------------------------------------


class TestDuckDBBackend:
    def test_upsert_and_list(self, duckdb_backend):
        row = {
            "panel_id": "test-panel-1",
            "panel_type": "real",
            "asset_class": "equity",
            "symbols": ["SPY", "QQQ"],
            "source": "yahoo",
            "panel_hash": "abc123",
            "manifest_json": '{"test": true}',
        }
        affected = duckdb_backend.upsert("panels", [row], conflict_keys=["panel_id"])
        assert affected == 1
        panels = duckdb_backend.list("panels")
        assert len(panels) == 1
        assert panels[0]["panel_id"] == "test-panel-1"

    def test_upsert_conflict_updates(self, duckdb_backend):
        row1 = {
            "panel_id": "p1",
            "panel_type": "manifest",
            "asset_class": "equity",
            "symbols": [],
            "source": "yahoo",
            "panel_hash": "hash1",
            "manifest_json": "{}",
        }
        duckdb_backend.upsert("panels", [row1], conflict_keys=["panel_id"])
        row2 = dict(row1, panel_hash="hash2")
        duckdb_backend.upsert("panels", [row2], conflict_keys=["panel_id"])
        panels = duckdb_backend.list("panels", filters={"panel_id": "p1"})
        assert len(panels) == 1
        assert panels[0]["panel_hash"] == "hash2"

    def test_delete(self, duckdb_backend):
        row = {
            "panel_id": "del-me",
            "panel_type": "manifest",
            "asset_class": "",
            "symbols": [],
            "source": "",
            "panel_hash": "x",
            "manifest_json": "{}",
        }
        duckdb_backend.upsert("panels", [row], conflict_keys=["panel_id"])
        deleted = duckdb_backend.delete("panels", {"panel_id": "del-me"})
        assert deleted == 1
        assert duckdb_backend.list("panels", filters={"panel_id": "del-me"}) == []

    def test_query(self, duckdb_backend):
        row = {
            "panel_id": "q1",
            "panel_type": "real",
            "asset_class": "commodity",
            "symbols": ["GLD"],
            "source": "polygon",
            "panel_hash": "h",
            "manifest_json": "{}",
        }
        duckdb_backend.upsert("panels", [row], conflict_keys=["panel_id"])
        results = duckdb_backend.query("SELECT panel_id FROM panels WHERE panel_id = $1", ["q1"])
        assert len(results) == 1
        assert results[0]["panel_id"] == "q1"

    def test_delete_requires_filter(self, duckdb_backend):
        with pytest.raises(ValueError):
            duckdb_backend.delete("panels", {})


# ---------------------------------------------------------------------------
# Polars StorageBackend CRUD
# ---------------------------------------------------------------------------


class TestPolarsBackend:
    def test_upsert_and_list(self, polars_backend):
        rows = [{"symbol": "SPY", "source": "yahoo", "freq": "1d", "row_count": 100}]
        affected = polars_backend.upsert("data_registry", rows, conflict_keys=["symbol", "source", "freq"])
        assert affected == 1
        result = polars_backend.list("data_registry")
        assert len(result) == 1

    def test_upsert_conflict_replaces(self, polars_backend):
        r1 = [{"symbol": "SPY", "source": "yahoo", "freq": "1d", "row_count": 100}]
        r2 = [{"symbol": "SPY", "source": "yahoo", "freq": "1d", "row_count": 200}]
        polars_backend.upsert("data_registry", r1, conflict_keys=["symbol", "source", "freq"])
        polars_backend.upsert("data_registry", r2, conflict_keys=["symbol", "source", "freq"])
        result = polars_backend.list("data_registry")
        assert len(result) == 1
        assert result[0]["row_count"] == 200

    def test_delete(self, polars_backend):
        rows = [{"symbol": "QQQ", "source": "yahoo", "freq": "1d", "row_count": 50}]
        polars_backend.upsert("data_registry", rows)
        deleted = polars_backend.delete("data_registry", {"symbol": "QQQ"})
        assert deleted == 1
        assert polars_backend.list("data_registry") == []


# ---------------------------------------------------------------------------
# Panel Store convenience functions
# ---------------------------------------------------------------------------


class TestPanelStore:
    def test_upsert_and_query(self):
        from pit_market.storage.panel_store import (
            upsert_panel, query_panel, list_panels, delete_panel, reset_panel_store,
        )
        reset_panel_store()
        upsert_panel("ps-1", panel_type="real", symbols=["SPY"], source="yahoo", panel_hash="h1")
        p = query_panel("ps-1")
        assert p is not None
        assert p["panel_id"] == "ps-1"
        panels = list_panels()
        assert len(panels) >= 1
        delete_panel("ps-1")
        assert query_panel("ps-1") is None

    def test_data_registry(self):
        from pit_market.storage.panel_store import (
            upsert_data_registry, get_data_registry, reset_panel_store,
        )
        from datetime import UTC, datetime
        reset_panel_store()
        upsert_data_registry("GLD", source="yahoo", freq="1d", last_fetched_at=datetime.now(UTC), row_count=500)
        entry = get_data_registry("GLD", source="yahoo", freq="1d")
        assert entry is not None
        assert entry["row_count"] == 500


# ---------------------------------------------------------------------------
# Concurrent write stress test (R-13)
# ---------------------------------------------------------------------------


class TestConcurrentWrites:
    def test_two_threads_upsert_no_lock_error(self):
        """2 threads simultaneously upsert — must not raise 'database is locked'."""
        from pit_market.storage.duckdb_backend import DuckDBStorageBackend
        backend = DuckDBStorageBackend()
        errors: list[Exception] = []

        def writer(thread_id: int):
            try:
                for i in range(20):
                    row = {
                        "panel_id": f"concurrent-{thread_id}-{i}",
                        "panel_type": "real",
                        "asset_class": "test",
                        "symbols": [],
                        "source": "test",
                        "panel_hash": f"h{thread_id}{i}",
                        "manifest_json": "{}",
                    }
                    backend.upsert("panels", [row], conflict_keys=["panel_id"])
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer, args=(1,))
        t2 = threading.Thread(target=writer, args=(2,))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
        assert errors == [], f"concurrent write errors: {errors}"
        # Verify all 40 rows present
        panels = backend.list("panels", limit=100)
        concurrent_panels = [p for p in panels if p["panel_id"].startswith("concurrent-")]
        assert len(concurrent_panels) == 40


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_duckdb_implements_protocol(self):
        from pit_market.storage.backend import StorageBackend
        from pit_market.storage.duckdb_backend import DuckDBStorageBackend
        assert isinstance(DuckDBStorageBackend(), StorageBackend)

    def test_polars_implements_protocol(self):
        from pit_market.storage.backend import StorageBackend
        from pit_market.storage.polars_backend import PolarsStorageBackend
        assert isinstance(PolarsStorageBackend(), StorageBackend)


# ---------------------------------------------------------------------------
# Default path fallback
# ---------------------------------------------------------------------------


class TestDefaultPath:
    def test_missing_env_uses_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PIT_DUCKDB_PATH", raising=False)
        from pit_market.storage.duckdb_engine import _resolve_db_path
        path = _resolve_db_path()
        assert path.endswith("pit.duckdb")
