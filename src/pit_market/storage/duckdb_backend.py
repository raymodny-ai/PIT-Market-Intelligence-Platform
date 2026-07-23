"""DuckDB StorageBackend implementation (T-37).

Implements the ``StorageBackend`` Protocol using DuckDB as the storage engine.
All writes are serialised through the process-level lock in ``duckdb_engine``.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pit_market.storage import duckdb_engine

log = logging.getLogger(__name__)


class DuckDBStorageBackend:
    """DuckDB-backed StorageBackend (discipline #9)."""

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return duckdb_engine.execute_read(sql, params)

    def upsert(
        self,
        table: str,
        rows: list[dict[str, Any]],
        conflict_keys: list[str] | None = None,
    ) -> int:
        if not rows:
            return 0
        # DuckDB uses positional ? placeholders
        columns = list(rows[0].keys())
        placeholders = ", ".join("?" for _ in columns)
        col_list = ", ".join(columns)

        if conflict_keys:
            update_clause = ", ".join(
                f"{c} = EXCLUDED.{c}" for c in columns if c not in conflict_keys
            )
            conflict_cols = ", ".join(conflict_keys)
            sql = (
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_clause}"
            )
        else:
            sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"

        conn = duckdb_engine.get_connection()
        lock = duckdb_engine.get_write_lock()
        affected = 0
        with lock:
            for row in rows:
                # Serialise dict/json values to JSON strings, build ordered param list
                values: list[Any] = []
                for c in columns:
                    v = row[c]
                    if isinstance(v, (dict, list)):
                        values.append(json.dumps(v, default=str, ensure_ascii=False))
                    else:
                        values.append(v)
                conn.execute(sql, values)
                affected += 1
        return affected

    def list(
        self,
        table: str,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where = ""
        params: list[Any] = []
        if filters:
            clauses = [f"{k} = ?" for k in filters]
            where = "WHERE " + " AND ".join(clauses)
            params = list(filters.values())
        sql = f"SELECT * FROM {table} {where} LIMIT {limit}"
        return duckdb_engine.execute_read(sql, params if params else None)

    def delete(self, table: str, filters: dict[str, Any]) -> int:
        if not filters:
            raise ValueError("delete requires at least one filter")
        clauses = [f"{k} = ?" for k in filters]
        where = " AND ".join(clauses)
        sql = f"DELETE FROM {table} WHERE {where}"
        params = list(filters.values())
        conn = duckdb_engine.get_connection()
        lock = duckdb_engine.get_write_lock()
        with lock:
            result = conn.execute(sql, params)
            return result.fetchone()[0] if result.description else 0

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        duckdb_engine.execute_write(sql, params)
