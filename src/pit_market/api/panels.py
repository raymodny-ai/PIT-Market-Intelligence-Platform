"""PIT Panel & Slice API endpoints (TODO T-10 / T-14).

Endpoints:
- GET  /v1/panels                  (list all manifests — used by PanelSwitcher)
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
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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


# Panel manifest discovery accepts two on-disk layouts:
#   1) flat:        {panels_dir}/{panel_id}_manifest.json        (CLI writes this)
#   2) nested:      {panels_dir}/{panel_id}/panel_manifest.json   (legacy/manual)
# Both paths resolve to the same JSON; we pick by mtime (newest wins).


def _find_panel_manifest(panel_id: str | None = None) -> list[Path]:
    """Return manifests matching panel_id (or all), newest first.

    If panel_id is None, return all manifests (used by /panels/latest).
    """
    if _PANELS_DIR is None or not _PANELS_DIR.exists():
        return []
    if panel_id is None:
        candidates = list(_PANELS_DIR.rglob("*manifest.json"))
    else:
        # Match both flat `{id}_manifest.json` and nested `{id}/panel_manifest.json`.
        candidates = list(_PANELS_DIR.rglob(f"{panel_id}*manifest.json"))
        # Also try the nested layout explicitly in case rglob above missed it.
        candidates += list(_PANELS_DIR.rglob(f"{panel_id}/panel_manifest.json"))
    # Deduplicate by resolved path.
    seen: set[Path] = set()
    unique: list[Path] = []
    for c in candidates:
        rp = c.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(c)
    unique.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return unique


@router.get("/panels")
def list_panels() -> dict:
    """List all panel manifests (newest first).

    Used by the frontend PanelSwitcher to populate its dropdown. Skips files
    that fail to parse so a single bad manifest doesn't break the listing.
    """
    if _PANELS_DIR is None or not _PANELS_DIR.exists():
        return {"panels": [], "count": 0}
    manifests = _find_panel_manifest()
    out = []
    for path in manifests:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Attach filesystem metadata so the UI can show file mtime/size.
            stat = path.stat()
            data["_path"] = str(path.relative_to(_PANELS_DIR))
            data["_mtime_utc"] = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
            data["_size_bytes"] = stat.st_size
            out.append(data)
        except Exception:  # noqa: BLE001 — surface count but skip the bad one
            continue
    return {"panels": out, "count": len(out)}


@router.get("/panels/latest")
def get_latest_panel() -> dict:
    manifests = _find_panel_manifest()
    if not manifests:
        raise HTTPException(status_code=404, detail="No panels built yet")
    return json.loads(manifests[0].read_text(encoding="utf-8"))


@router.get("/panels/{panel_id}")
def get_panel(panel_id: str) -> dict:
    if _PANELS_DIR is None:
        raise HTTPException(status_code=503, detail="Panels dir not configured")
    matches = _find_panel_manifest(panel_id)
    if not matches:
        raise HTTPException(status_code=404, detail=f"Panel not found: {panel_id}")
    return json.loads(matches[0].read_text(encoding="utf-8"))


@router.post("/panels/{panel_id}/slice")
def slice_panel(panel_id: str, req: SliceRequest) -> dict:
    if _PANELS_DIR is None:
        raise HTTPException(status_code=503, detail="Panels dir not configured")
    try:
        req.validate_against_registry()
    except RegistryError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    panel_path = next(_PANELS_DIR.rglob(f"{panel_id}*value_panel.parquet"), None)
    if panel_path is None:
        # Fall back to looking under a {panel_id}/ subdirectory (legacy layout).
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


@router.post("/panels/replay")
def replay_panel(req: SliceRequest) -> dict:
    raise HTTPException(status_code=501, detail="PIT replay not yet implemented; see T-14 follow-up")


# =============================================================================
# Registry endpoints
# =============================================================================


@router.get("/metrics/registry")
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


@router.get("/instruments/registry")
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


@router.post("/runs/{run_id}/start")
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


@router.post("/runs/{run_id}/progress")
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


@router.get("/runs/{run_id}/stream")
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
