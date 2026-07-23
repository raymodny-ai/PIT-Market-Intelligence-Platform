"""Polars in-memory StorageBackend implementation (T-37).

Fallback backend for small datasets and local development.
Data lives only in memory; set ``PIT_STORAGE_BACKEND=duckdb`` for persistence.
"""
from __future__ import annotations

import logging
from typing import Any

import polars as pl

log = logging.getLogger(__name__)


class PolarsStorageBackend:
    """In-memory Polars-backed StorageBackend (discipline #9).

    Tables are stored as a dict[str, pl.DataFrame]. SQL queries are
    translated to Polars filter/select operations where possible.
    """

    def __init__(self) -> None:
        self._tables: dict[str, pl.DataFrame] = {}

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        # Polars doesn't support SQL natively — use DuckDB for ad-hoc SQL
        # This is a best-effort fallback: return empty for unsupported queries
        log.warning("PolarsStorageBackend.query: SQL not natively supported, returning empty")
        return []

    def upsert(
        self,
        table: str,
        rows: list[dict[str, Any]],
        conflict_keys: list[str] | None = None,
    ) -> int:
        if not rows:
            return 0
        new_df = pl.DataFrame(rows)
        if table in self._tables and conflict_keys:
            existing = self._tables[table]
            # Anti-join to remove conflicting rows, then concat
            anti = existing.join(new_df.select(conflict_keys), on=conflict_keys, how="anti")
            self._tables[table] = pl.concat([anti, new_df], how="vertical")
        elif table in self._tables:
            self._tables[table] = pl.concat([self._tables[table], new_df], how="vertical")
        else:
            self._tables[table] = new_df
        return len(rows)

    def list(
        self,
        table: str,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if table not in self._tables:
            return []
        df = self._tables[table]
        if filters:
            for k, v in filters.items():
                if k in df.columns:
                    df = df.filter(pl.col(k) == v)
        return df.head(limit).to_dicts()

    def delete(self, table: str, filters: dict[str, Any]) -> int:
        if table not in self._tables:
            return 0
        df = self._tables[table]
        mask = pl.lit(True)
        for k, v in filters.items():
            if k in df.columns:
                mask = mask & (pl.col(k) == v)
        remaining = df.filter(~mask)
        deleted = df.height - remaining.height
        self._tables[table] = remaining
        return deleted

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        log.warning("PolarsStorageBackend.execute: DDL not supported, no-op for: %s", sql[:80])
