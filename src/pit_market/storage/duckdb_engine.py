"""DuckDB connection singleton with concurrency protection (T-37).

- Single connection per process, path from ``PIT_DUCKDB_PATH`` env.
- ``threading.Lock`` serialises all writes to prevent ``database is locked``.
- Falls back to ``data/pit.duckdb`` when env is unset.
- ``get_connection()`` is idempotent and thread-safe.
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
from pathlib import Path
from typing import Any

import duckdb

log = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "data/pit.duckdb"

_lock = threading.Lock()
_connection: duckdb.DuckDBPyConnection | None = None
_db_path: str | None = None


def _resolve_db_path() -> str:
    """Resolve DuckDB file path from env or default."""
    path = os.environ.get("PIT_DUCKDB_PATH", _DEFAULT_DB_PATH)
    # Ensure parent directory exists
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)
    return str(Path(path).resolve())


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return the singleton DuckDB connection (thread-safe, lazy-init)."""
    global _connection, _db_path
    with _lock:
        target_path = _resolve_db_path()
        if _connection is not None and _db_path == target_path:
            return _connection
        # Path changed or first call — (re)open
        if _connection is not None:
            with contextlib.suppress(Exception):  # pragma: no cover
                _connection.close()
        log.info("opening DuckDB connection: %s", target_path)
        _connection = duckdb.connect(target_path, config={"threads": os.cpu_count() or 2})
        _db_path = target_path
        # Run migrations on first connect
        _run_migrations(_connection)
        return _connection


def get_write_lock() -> threading.Lock:
    """Expose the process-level write lock for callers that need
    serialised multi-statement transactions."""
    return _lock


def execute_write(sql: str, params: dict[str, Any] | None = None) -> None:
    """Execute a write statement under the process-level lock."""
    conn = get_connection()
    with _lock:
        if params:
            conn.execute(sql, params)
        else:
            conn.execute(sql)


def execute_read(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute a read query and return rows as list of dicts."""
    conn = get_connection()
    # Reads do not need the write lock — DuckDB allows concurrent readers
    result = conn.execute(sql, params) if params else conn.execute(sql)
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]


def close() -> None:
    """Close the singleton connection (for tests / shutdown)."""
    global _connection, _db_path
    with _lock:
        if _connection is not None:
            with contextlib.suppress(Exception):  # pragma: no cover
                _connection.close()
            _connection = None
            _db_path = None


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _run_migrations(conn: duckdb.DuckDBPyConnection) -> None:
    """Run SQL migration files in lexicographic order.

    Each migration is idempotent (uses ``CREATE TABLE IF NOT EXISTS``).
    A ``_migrations`` meta-table tracks which have been applied.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            migration_id VARCHAR PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    applied = {
        row[0]
        for row in conn.execute("SELECT migration_id FROM _migrations").fetchall()
    }
    if not _MIGRATIONS_DIR.exists():
        return
    for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        migration_id = sql_file.stem
        if migration_id in applied:
            continue
        log.info("applying migration: %s", migration_id)
        sql = sql_file.read_text(encoding="utf-8")
        conn.execute(sql)
        conn.execute(
            "INSERT INTO _migrations (migration_id) VALUES (?)",
            [migration_id],
        )
