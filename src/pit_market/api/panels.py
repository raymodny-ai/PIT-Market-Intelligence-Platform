"""PIT Panel & Slice API endpoints (TODO T-10 / T-14).

Endpoints:
- GET  /v1/panels/latest
- GET  /v1/panels/{panel_id}
- POST /v1/panels/{panel_id}/slice
- POST /v1/panels/replay
- GET  /v1/metrics/registry
- GET  /v1/instruments/registry
- POST /v1/runs/{run_id}/start
- POST /v1/runs/{run_id}/progress
- GET  /v1/runs/{run_id}/stream (SSE)
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import polars as pl
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from pit_market.storage.cache import CacheBackend, InProcessCache, make_cache_key
from pit_market.storage.registry import Registry, RegistryError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["panels"])


_REGISTRY: Registry | None = None
_PANELS_DIR: Path | None = None
_CACHE: CacheBackend | None = None
_RUN_PROGRESS: dict[str, list[dict[str, Any]]] = {}


def configure(reg: Registry, panels_dir: str | Path, cache: CacheBackend | None = None) -> None:
    global _REGISTRY, _PANELS_DIR, _CACHE
    _REGISTRY = reg
    _PANELS_DIR = Path(panels_dir)
    _CACHE = cache or InProcessCache()


def _find_panel_manifest(panel_id: str) -> list[Path]:
    """Locate manifest files for ``panel_id`` on disk.

    Supports three layouts produced by different builders:
      * nested:  ``<root>/<panel_id>/panel_manifest.json`` (T-10+ full builder)
      * flat:    ``<root>/<panel_id>_manifest.json`` (CLI flat builder)
      * loose:   ``<root>/<panel_id>/manifest.json`` (a few legacy paths)

    Returns a list (sorted, mtime-newest first) so callers can pick the
    canonical entry. Empty list means not found.
    """
    if _PANELS_DIR is None:
        return []
    candidates = (
        list(_PANELS_DIR.rglob(f"{panel_id}/panel_manifest.json"))
        + list(_PANELS_DIR.glob(f"{panel_id}_manifest.json"))
        + list(_PANELS_DIR.rglob(f"{panel_id}/manifest.json"))
    )
    # De-dup (rglob + glob may overlap) and sort by mtime descending
    seen: set[Path] = set()
    unique: list[Path] = []
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        unique.append(c)
    unique.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return unique


def _get_registry() -> Registry:
    if _REGISTRY is None:
        raise ValueError("Registry not configured (lifespan not started)")
    return _REGISTRY


# =============================================================================
# Schemas
# =============================================================================


VALID_DOMAINS = {"price", "position", "flow", "otc", "macro", "volatility", "quality"}
VALID_SOURCES = {"yfinance", "fred", "cftc", "finra", "sec", "cboe", "etf_issuer"}
VALID_FREQUENCIES = {"daily", "weekly", "monthly", "quarterly", "event"}
VALID_STATES = {
    "LOW_EXTREME", "LOW", "NEUTRAL", "HIGH", "HIGH_EXTREME",
    "MISSING", "STALE", "INFERRED_AVAILABILITY",
}


class SliceRequest(BaseModel):
    panel_id: str | None = None
    as_of: str | None = None
    decision_clock: str = "1805_ET"
    universe: list[str] = Field(min_length=1, max_length=50)
    date_range: dict | None = None
    domains: list[str] | None = None
    fields: list[str] | None = None
    sources: list[str] | None = None
    frequencies: list[str] | None = None
    states: list[str] | None = None
    quality: dict | None = None
    aggregation: dict | None = None
    sort: dict | None = None
    page: dict | None = None

    @field_validator("decision_clock")
    @classmethod
    def _validate_clock(cls, v: str) -> str:
        if v not in {"1605_ET", "1805_ET"}:
            raise ValueError("decision_clock must be 1605_ET or 1805_ET")
        return v

    @field_validator("domains")
    @classmethod
    def _validate_domains(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for d in v:
            if d not in VALID_DOMAINS:
                raise ValueError(f"invalid domain: {d!r}; must be one of {sorted(VALID_DOMAINS)}")
        return v

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for s in v:
            if s not in VALID_SOURCES:
                raise ValueError(f"invalid source: {s!r}")
        return v

    @field_validator("frequencies")
    @classmethod
    def _validate_frequencies(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for f in v:
            if f not in VALID_FREQUENCIES:
                raise ValueError(f"invalid frequency: {f!r}")
        return v

    @field_validator("states")
    @classmethod
    def _validate_states(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for s in v:
            if s not in VALID_STATES:
                raise ValueError(f"invalid state: {s!r}")
        return v

    @field_validator("page")
    @classmethod
    def _validate_page(cls, v: dict | None) -> dict | None:
        if v is None:
            return v
        offset = v.get("offset", 0)
        limit = v.get("limit", 100)
        if not (0 <= offset <= 100_000):
            raise ValueError("page.offset out of range")
        if not (1 <= limit <= 500):
            raise ValueError("page.limit must be 1..500")
        return v

    def validate_against_registry(self) -> None:
        reg = _get_registry()
        for sym in self.universe:
            reg.assert_canonical_symbol(sym)
        if self.fields:
            for fn in self.fields:
                reg.assert_field_name(fn)


# =============================================================================
# Panels
# =============================================================================


@router.get(
    "/panels/latest",
    summary="Get latest panel",
    description="Return the most recently built PIT panel manifest.",
    tags=["panels"],
    responses={404: {"description": "No panels built yet"}},
)
def get_latest_panel() -> dict:
    if _PANELS_DIR is None or not _PANELS_DIR.exists():
        raise HTTPException(status_code=404, detail="No panels built yet")
    manifests = sorted(_PANELS_DIR.rglob("panel_manifest.json"), reverse=True)
    if not manifests:
        raise HTTPException(status_code=404, detail="No panels built yet")
    return json.loads(manifests[0].read_text(encoding="utf-8"))


@router.get(
    "/panels/{panel_id}",
    summary="Get panel by ID",
    description="Retrieve a specific PIT panel manifest by its panel_id.",
    tags=["panels"],
    responses={404: {"description": "Panel not found"}, 503: {"description": "Panels dir not configured"}},
)
def get_panel(panel_id: str) -> dict:
    if _PANELS_DIR is None:
        raise HTTPException(status_code=503, detail="Panels dir not configured")

    # DuckDB first (Phase 6 panels)
    try:
        from pit_market.storage.panel_store import query_panel
        db_panel = query_panel(panel_id)
        if db_panel is not None:
            return db_panel
    except Exception:
        pass

    # Filesystem fallback: try directory layout, then flat manifest
    matches = list(_PANELS_DIR.rglob(f"{panel_id}/panel_manifest.json"))
    if not matches:
        flat = _PANELS_DIR / f"{panel_id}_manifest.json"
        if flat.exists():
            return json.loads(flat.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail=f"Panel not found: {panel_id}")
    return json.loads(matches[0].read_text(encoding="utf-8"))


@router.post(
    "/panels/{panel_id}/slice",
    summary="Slice panel data",
    description="Apply filters, sorting, and pagination to a PIT panel. Returns filtered rows.",
    tags=["panels"],
    responses={400: {"description": "Registry validation failed"}, 404: {"description": "Panel not found"}},
)
def slice_panel(panel_id: str, req: SliceRequest) -> dict:
    if _PANELS_DIR is None:
        raise HTTPException(status_code=503, detail="Panels dir not configured")
    try:
        req.validate_against_registry()
    except RegistryError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    panel_path = next(_PANELS_DIR.rglob(f"{panel_id}/value_panel.parquet"), None)
    if panel_path is None:
        raise HTTPException(status_code=404, detail=f"Panel not found: {panel_id}")
    df = pl.read_parquet(str(panel_path))

    df = df.filter(pl.col("canonical_symbol").is_in(req.universe))
    if req.fields:
        df = df.filter(pl.col("field_name").is_in(req.fields))
    if req.sources:
        df = df.filter(pl.col("source_name").is_in(req.sources))
    if req.frequencies:
        df = df.filter(pl.col("frequency").is_in(req.frequencies))
    if req.sort:
        field = req.sort["field"]
        direction = req.sort.get("direction", "asc")
        df = df.sort(field, descending=(direction == "desc"))
    if req.page:
        offset = int(req.page.get("offset", 0))
        limit = int(req.page.get("limit", 100))
        df = df.slice(offset, limit)

    rows = df.to_dicts()
    cache_key = make_cache_key(panel_id, req.model_dump(exclude_none=True))
    if _CACHE is not None:
        _CACHE.set(cache_key, rows, ttl_sec=900)

    return {
        "slice_id": f"slice_{cache_key[:8]}",
        "panel_id": panel_id,
        "row_count": df.height,
        "rows": rows,
        "cache_key": cache_key,
    }


@router.post(
    "/panels/replay",
    summary="Replay PIT panel",
    description="Replay an existing panel build (idempotent re-run). Not yet implemented.",
    tags=["panels"],
    responses={501: {"description": "Not yet implemented"}},
)
def replay_panel(req: SliceRequest) -> dict:
    raise HTTPException(status_code=501, detail="PIT replay not yet implemented; see T-14 follow-up")


# =============================================================================
# Registry endpoints
# =============================================================================


@router.get(
    "/metrics/registry",
    summary="Metric registry",
    description="List all registered metric fields with their metadata.",
    tags=["registry"],
    responses={503: {"description": "Registry not configured"}},
)
def metrics_registry() -> dict:
    if _REGISTRY is None:
        raise HTTPException(status_code=503, detail="Registry not configured")
    return {
        "metric_registry_version": "metrics.v1.0",
        "fields": {
            fn: {
                "display_name_zh": m.display_name_zh,
                "source_name": m.source_name,
                "dataset_name": m.dataset_name,
                "frequency": m.frequency,
                "unit": m.unit,
                "availability_rule_id": m.availability_rule_id,
                "max_staleness": m.max_staleness,
                "forward_fill_allowed": m.forward_fill_allowed,
                "semantic_warning": m.semantic_warning,
                "feature_definition_id": m.feature_definition_id,
            }
            for fn, m in _REGISTRY.metrics.items()
        },
    }


@router.get(
    "/instruments/registry",
    summary="Instrument registry",
    description="List all registered instruments with their metadata.",
    tags=["registry"],
    responses={503: {"description": "Registry not configured"}},
)
def instruments_registry() -> dict:
    if _REGISTRY is None:
        raise HTTPException(status_code=503, detail="Registry not configured")
    return {
        "registry_version": "registry.v1.0",
        "instruments": {
            sym: {
                "asset_class": i.asset_class,
                "primary_market": i.primary_market,
                "vendor_symbol_yfinance": i.vendor_symbol_yfinance,
                "cftc_market_code": i.cftc_market_code,
                "cot_report_type": i.cot_report_type,
                "issuer": i.issuer,
                "related_etfs": list(i.related_etfs),
                "timezone": i.timezone,
                "display_name_zh": i.display_name_zh,
                "display_name_en": i.display_name_en,
            }
            for sym, i in _REGISTRY.instruments.items()
        },
    }


# =============================================================================
# SSE: run progress (T-14)
# =============================================================================


@router.post(
    "/runs/{run_id}/start",
    summary="Start SSE run",
    description="Initialize an SSE progress stream for a PIT panel build or ETL run.",
    tags=["sse"],
)
def start_run(run_id: str) -> dict:
    _RUN_PROGRESS[run_id] = [{
        "event": "run_status",
        "id": f"{run_id}:0",
        "data": {
            "run_id": run_id,
            "status": "QUEUED",
            "progress_pct": 0,
            "message_zh": "排队中",
        },
    }]
    return {"run_id": run_id, "status": "QUEUED"}


@router.post(
    "/runs/{run_id}/progress",
    summary="Push progress event",
    description="Push a progress event to the SSE stream for a running job.",
    tags=["sse"],
)
def push_progress(run_id: str, status: str, progress_pct: int, message_zh: str = "") -> dict:
    if run_id not in _RUN_PROGRESS:
        _RUN_PROGRESS[run_id] = []
    events = _RUN_PROGRESS[run_id]
    events.append({
        "event": "run_status",
        "id": f"{run_id}:{len(events)}",
        "data": {
            "run_id": run_id,
            "status": status,
            "progress_pct": progress_pct,
            "message_zh": message_zh,
        },
    })
    return {"run_id": run_id, "status": status, "event_count": len(events)}


@router.get(
    "/runs/{run_id}/stream",
    summary="SSE progress stream",
    description="Server-Sent Events stream with Last-Event-ID resume support.",
    tags=["sse"],
)
async def stream_run(
    run_id: str,
    request: Request,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """SSE stream with Last-Event-ID resume support (T-14)."""

    async def event_gen() -> AsyncIterator[bytes]:
        start_idx = 0
        if last_event_id:
            try:
                _, idx = last_event_id.split(":")
                start_idx = int(idx) + 1
            except (ValueError, AttributeError):
                start_idx = 0
        events = _RUN_PROGRESS.get(run_id, [])
        i = start_idx
        while i < len(events):
            if await request.is_disconnected():
                break
            ev = events[i]
            yield (
                f"id: {ev['id']}\n"
                f"event: {ev['event']}\n"
                f"data: {json.dumps(ev['data'])}\n\n"
            ).encode()
            i += 1
            await asyncio.sleep(0.05)
        if i >= len(events):
            yield b": keepalive\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# =============================================================================
# T-38: DuckDB SQL endpoint + Registry search + Panel store integration
# =============================================================================


class SQLRequest(BaseModel):
    sql: str = Field(..., description="Read-only SQL query")


class ErrorDetail(BaseModel):
    error_code: str
    message: str
    details: dict = Field(default_factory=dict)


@router.post(
    "/sql",
    summary="Execute read-only DuckDB SQL (dev mode only)",
    description="Execute a read-only SQL query against DuckDB. Disabled in production.",
    tags=["admin"],
    response_model=dict,
    responses={
        403: {"description": "Disabled in production mode", "model": ErrorDetail},
        400: {"description": "Invalid SQL", "model": ErrorDetail},
        408: {"description": "Query timeout (>30s)", "model": ErrorDetail},
    },
)
def execute_sql(req: SQLRequest) -> dict:
    """Execute read-only DuckDB SQL (discipline #9: dev mode only)."""
    import os
    env = os.environ.get("ENV", "development").lower()
    if env != "development":
        raise HTTPException(
            status_code=403,
            detail={"error_code": "SQL_DISABLED", "message": "/sql endpoint disabled in production mode"},
        )

    # Basic safety: reject write statements
    sql_upper = req.sql.strip().upper()
    write_keywords = ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE")
    for kw in write_keywords:
        if sql_upper.startswith(kw):
            raise HTTPException(
                status_code=400,
                detail={"error_code": "WRITE_FORBIDDEN", "message": f"Write operations not allowed: {kw}"},
            )

    try:
        from pit_market.storage import duckdb_engine
        # Timeout: 30s (implemented via DuckDB statement_timeout)
        conn = duckdb_engine.get_connection()
        conn.execute("SET statement_timeout = '30s'")
        result = conn.execute(req.sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchmany(10000)
        truncated = False
        if result.fetchone() is not None:
            truncated = True
        return {
            "columns": columns,
            "rows": [dict(zip(columns, row, strict=False)) for row in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail={"error_code": "SQL_ERROR", "message": str(e)}) from e


@router.get(
    "/registry/search",
    summary="Search instrument registry",
    description="Fuzzy search across canonical symbols and display names.",
    tags=["registry"],
    response_model=dict,
    responses={
        200: {"description": "Search results"},
    },
)
def search_registry(q: str = "") -> dict:
    """Symbol fuzzy search in instrument registry (T-38, for T-51 frontend)."""
    if _REGISTRY is None:
        raise HTTPException(status_code=503, detail="Registry not configured")
    query = q.lower().strip()
    results = []
    for sym, inst in _REGISTRY.instruments.items():
        searchable = f"{sym} {inst.display_name_en} {inst.display_name_zh} {inst.asset_class or ''}".lower()
        if not query or query in searchable:
            results.append({
                "symbol": sym,
                "asset_class": inst.asset_class,
                "display_name_en": inst.display_name_en,
                "display_name_zh": inst.display_name_zh,
                "vendor_symbol_yfinance": inst.vendor_symbol_yfinance,
            })
    return {"query": q, "count": len(results), "results": results}


@router.get(
    "/panels",
    summary="List all panels",
    description="List all panels from DuckDB storage (T-38 integration).",
    tags=["panels"],
    response_model=dict,
)
def list_all_panels() -> dict:
    """List all panels.

    Source-of-truth is DuckDB (T-38+). Legacy CLI manifest-only panels
    (data/gold/pit_panels/<id>_manifest.json or <id>/panel_manifest.json)
    are merged in so historical panels remain visible to the API.
    """
    db_panels: list[dict[str, Any]] = []
    try:
        from pit_market.storage.panel_store import list_panels
        db_panels = list_panels() or []
    except Exception:
        # DuckDB unavailable — fall back to filesystem scan below.
        pass

    fs_panels: list[dict[str, Any]] = []
    if _PANELS_DIR is not None and _PANELS_DIR.exists():
        manifests = (
            list(_PANELS_DIR.rglob("panel_manifest.json"))
            + list(_PANELS_DIR.rglob("manifest.json"))
            + list(_PANELS_DIR.rglob("*_manifest.json"))
        )
        seen_ids: set[str] = set()
        for p in db_panels:
            pid = p.get("panel_id")
            if pid:
                seen_ids.add(pid)
        for m in manifests:
            try:
                data = json.loads(m.read_text(encoding="utf-8"))
            except Exception:
                continue
            pid = data.get("panel_id") or m.parent.name
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            fs_panels.append(data)

    panels = db_panels + fs_panels
    return {"panels": panels, "count": len(panels)}
