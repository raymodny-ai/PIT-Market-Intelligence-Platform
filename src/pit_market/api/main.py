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
app.include_router(panels_api.router)
app.include_router(export_api.export_router)
app.include_router(analyses_api.router)
app.include_router(lineage_api.router)


# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "registry_hash": getattr(app.state, "registry", None) and app.state.registry.registry_hash,
    }
