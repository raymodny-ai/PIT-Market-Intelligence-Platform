"""StorageBackend Protocol (T-37, discipline #9).

All business code MUST access persistent data through this Protocol.
Direct ``import duckdb`` or ``polars.read_parquet`` in business layers is
forbidden — use ``PIT_STORAGE_BACKEND=duckdb|polars`` to switch backends.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Stable storage interface — DuckDB and Polars both implement this."""

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a read query and return rows as dicts."""
        ...

    def upsert(self, table: str, rows: list[dict[str, Any]], conflict_keys: list[str] | None = None) -> int:
        """Insert or update rows. Returns affected row count."""
        ...

    def list(self, table: str, filters: dict[str, Any] | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List rows from a table with optional equality filters."""
        ...

    def delete(self, table: str, filters: dict[str, Any]) -> int:
        """Delete rows matching filters. Returns deleted row count."""
        ...

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        """Execute a write DDL/DML statement (no return value)."""
        ...
