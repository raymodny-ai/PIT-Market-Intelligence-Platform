"""FastAPI application entry point — Phase 1 surface."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from pit_market import __version__
from pit_market.api import analyses as analyses_api
from pit_market.api import export as export_api
from pit_market.api import lineage as lineage_api
from pit_market.api import panels as panels_api
from pit_market.storage.cache import InProcessCache
from pit_market.storage.registry import Registry, RegistryError

_CONFIG_DIR = Path(os.environ.get("PIT_CONFIG_DIR", "config"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load Instrument / Metric / Schema registries at app start."""
    if not _CONFIG_DIR.is_absolute():
        _CONFIG_DIR.resolve()
    panels_dir = Path(os.environ.get("GOLD_PANELS_DIR", "./data/gold/pit_panels"))
    try:
        registry = Registry.load(_CONFIG_DIR)
        app.state.registry = registry
        cache = InProcessCache()
        panels_api.configure(registry, panels_dir, cache)
        analyses_api.configure(registry)
    except RegistryError as e:
        # Hard fail — registries are non-optional in PIT discipline
        raise RuntimeError(f"Registry load failed: {e}") from e
    yield


app = FastAPI(
    title="PIT Market Intelligence API",
    version=__version__,
    description="Phase 1: Panel / Slice / Registry endpoints.",
    lifespan=lifespan,
)

# CORS — allow the local Next.js dev frontend (port 8701) and any localhost origin.
# Browsers enforce CORS for cross-origin fetches even on the same host; without this,
# the frontend falls back to the empty-state branch because every fetch throws.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8701",
        "http://localhost:8701",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(panels_api.router)
app.include_router(export_api.export_router)
app.include_router(analyses_api.router)
app.include_router(lineage_api.router)


# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------


@app.get("/")
def root() -> dict:
    """API entry — list documented endpoints for the human eye / curl explorers."""
    return {
        "service": "PIT Market Intelligence API",
        "version": __version__,
        "endpoints": {
            "health": "GET /health",
            "openapi": "GET /openapi.json",
            "docs": "GET /docs (Swagger UI)",
            "instruments": "GET /v1/instruments/registry",
            "metrics": "GET /v1/metrics/registry",
            "panels_latest": "GET /v1/panels/latest",
            "panel_slice": "POST /v1/panels/{panel_id}/slice",
            "panel_replay": "POST /v1/panels/replay",
            "analyses_start": "POST /v1/analyses",
            "analyses_stream": "GET /v1/analyses/{run_id}/stream",
            "lineage": "GET /v1/lineage/{entity_id}",
            "lineage_facet": "GET /v1/lineage/analysis/{run_id}/facet",
            "sources_status": "GET /v1/sources/status",
            "source_events": "GET /v1/sources/{source_name}/events",
            "export": "GET /v1/export/panels/{panel_id}",
        },
    }


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "registry_hash": getattr(app.state, "registry", None) and app.state.registry.registry_hash,
    }
