"""Panel Store — CRUD operations for PIT panels (T-37).

Provides ``upsert_panel()``, ``query_panel()``, ``list_panels()``, ``delete_panel()``
backed by the ``StorageBackend`` Protocol.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from pit_market.storage.backend import StorageBackend


def _get_backend() -> StorageBackend:
    """Factory: return the active StorageBackend based on PIT_STORAGE_BACKEND env."""
    backend_env = os.environ.get("PIT_STORAGE_BACKEND", "duckdb").lower()
    if backend_env == "polars":
        from pit_market.storage.polars_backend import PolarsStorageBackend
        return PolarsStorageBackend()
    from pit_market.storage.duckdb_backend import DuckDBStorageBackend
    return DuckDBStorageBackend()


# Module-level backend singleton (lazy)
_backend: StorageBackend | None = None


def get_panel_store() -> StorageBackend:
    """Return the module-level panel store singleton."""
    global _backend
    if _backend is None:
        _backend = _get_backend()
    return _backend


def reset_panel_store() -> None:
    """Reset the singleton (for tests)."""
    global _backend
    _backend = None


# ---------------------------------------------------------------------------
# Panel-specific CRUD helpers (convenience wrappers over StorageBackend)
# ---------------------------------------------------------------------------


def upsert_panel(
    panel_id: str,
    panel_type: str = "manifest",
    asset_class: str | None = None,
    symbols: list[str] | None = None,
    source: str | None = None,
    panel_hash: str = "",
    manifest: dict[str, Any] | None = None,
) -> int:
    """Insert or update a panel record."""
    backend = get_panel_store()
    row = {
        "panel_id": panel_id,
        "panel_type": panel_type,
        "asset_class": asset_class or "",
        "symbols": symbols or [],
        "source": source or "",
        "updated_at": datetime.now(UTC).isoformat(),
        "panel_hash": panel_hash,
        "manifest_json": json.dumps(manifest or {}, default=str, ensure_ascii=False),
    }
    return backend.upsert("panels", [row], conflict_keys=["panel_id"])


def query_panel(panel_id: str) -> dict[str, Any] | None:
    """Fetch a single panel by ID."""
    backend = get_panel_store()
    rows = backend.list("panels", filters={"panel_id": panel_id}, limit=1)
    return rows[0] if rows else None


def list_panels(limit: int = 100) -> list[dict[str, Any]]:
    """List all panels."""
    backend = get_panel_store()
    return backend.list("panels", limit=limit)


def delete_panel(panel_id: str) -> int:
    """Delete a panel by ID."""
    backend = get_panel_store()
    return backend.delete("panels", {"panel_id": panel_id})


# ---------------------------------------------------------------------------
# Data Registry helpers (for T-36 incremental sync)
# ---------------------------------------------------------------------------


def upsert_data_registry(
    symbol: str,
    source: str = "yahoo",
    freq: str = "1d",
    last_fetched_at: datetime | None = None,
    row_count: int = 0,
    quality_flags: dict[str, Any] | None = None,
) -> int:
    """Insert or update a data_registry record."""
    backend = get_panel_store()
    row = {
        "symbol": symbol,
        "source": source,
        "freq": freq,
        "last_fetched_at": last_fetched_at.isoformat() if last_fetched_at else None,
        "row_count": row_count,
        "quality_flags_json": json.dumps(quality_flags or {}, default=str, ensure_ascii=False),
    }
    return backend.upsert(
        "data_registry", [row], conflict_keys=["symbol", "source", "freq"]
    )


def get_data_registry(
    symbol: str, source: str = "yahoo", freq: str = "1d"
) -> dict[str, Any] | None:
    """Fetch a data_registry entry."""
    backend = get_panel_store()
    rows = backend.list(
        "data_registry",
        filters={"symbol": symbol, "source": source, "freq": freq},
        limit=1,
    )
    return rows[0] if rows else None
