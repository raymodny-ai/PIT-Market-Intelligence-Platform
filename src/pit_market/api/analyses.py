"""Analyses API: LLM finding creation + SSE (TODO T-20 / T-23)."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import pit_market.api.panels as panels_api
from pit_market.evidence.catalog import EvidenceCatalogBuilder
from pit_market.llm.adapter import LLMAdapter, LLMProvider
from pit_market.llm.runner import AnalysisRunner, get_run_events
from pit_market.storage.registry import Registry

log = logging.getLogger(__name__)


# =============================================================================
# Panel resolution (shared between /evidence and /analyses endpoints)
# =============================================================================
# Panels live in one of two on-disk layouts:
#   1) flat:   {panels_dir}/{panel_id}_manifest.json                  (CLI)
#   2) nested: {panels_dir}/{panel_id}/panel_manifest.json + value_panel.parquet
#
# When a flat manifest exists but no parquet, we fall back to "manifest-only"
# mode: build an empty pl.DataFrame + return the manifest's decision_time.
# The LLM still produces a finding (e.g. "insufficient evidence"), which is
# more useful than 404 for CLI-built panels.


def _resolve_panel(panel_id: str) -> tuple[Path, dict, pl.DataFrame]:
    """Resolve a panel_id to (manifest_path, manifest_dict, value_df).

    Raises HTTPException(404) if no manifest exists. Returns an empty df
    if no parquet is present (manifest-only mode).
    """
    if panels_api._PANELS_DIR is None:
        raise HTTPException(status_code=503, detail="Panels dir not configured")
    matches = panels_api._find_panel_manifest(panel_id)
    if not matches:
        raise HTTPException(status_code=404, detail=f"Panel not found: {panel_id}")
    manifest_path = matches[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Flat layout: manifest_path = .../{panel_id}_manifest.json
    # Nested layout: manifest_path = .../{panel_id}/panel_manifest.json
    # Try to find value_panel.parquet as a sibling (nested) or anywhere in
    # the tree (legacy layouts). Use the *first* match.
    if panels_api._PANELS_DIR is not None:
        parquet_candidates = list(
            panels_api._PANELS_DIR.rglob(f"{panel_id}*value_panel.parquet")
        )
        if not parquet_candidates:
            parquet_candidates = list(
                panels_api._PANELS_DIR.rglob(f"{panel_id}/value_panel.parquet")
            )
    else:
        parquet_candidates = []
    if parquet_candidates:
        df = pl.read_parquet(str(parquet_candidates[0]))
    else:
        # Manifest-only mode: build an empty df with the expected schema so
        # EvidenceCatalogBuilder.build() returns an empty catalog rather than
        # crashing on a missing column.
        df = pl.DataFrame(schema={
            "canonical_symbol": pl.Utf8,
            "field_name": pl.Utf8,
            "value": pl.Float64,
            "observation_time": pl.Datetime(time_zone="UTC"),
            "available_at": pl.Datetime(time_zone="UTC"),
            "raw_record_hash": pl.Utf8,
            "source_name": pl.Utf8,
            "dataset_name": pl.Utf8,
            "feature_observation_id": pl.Utf8,
            "observation_id": pl.Utf8,
            "quality_status": pl.Utf8,
        })
    return manifest_path, manifest, df

router = APIRouter(prefix="/v1/analyses", tags=["analyses"])

_REGISTRY: Registry | None = None
_RUNNER: AnalysisRunner | None = None


def configure(reg: Registry, runner: AnalysisRunner | None = None) -> None:
    global _REGISTRY, _RUNNER
    _REGISTRY = reg
    _RUNNER = runner or AnalysisRunner()


def _get_registry() -> Registry:
    if _REGISTRY is None:
        raise ValueError("Registry not configured")
    return _REGISTRY


def _get_runner() -> AnalysisRunner:
    if _RUNNER is None:
        raise ValueError("Runner not configured")
    return _RUNNER


class AnalysisRequest(BaseModel):
    panel_id: str
    decision_time: str | None = None
    provider: str = "mock"
    model: str = "gpt-4o"


class EvidenceResponse(BaseModel):
    catalog_id: str
    catalog_sha256: str
    decision_time: str
    evidence_count: int
    sample: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/evidence/{panel_id}")
def build_evidence(panel_id: str) -> EvidenceResponse:
    _manifest_path, manifest, df = _resolve_panel(panel_id)
    # CLI manifests use decision_time_utc; nested manifests use decision_time.
    dt_str = manifest.get("decision_time") or manifest["decision_time_utc"]
    decision_time = datetime.fromisoformat(dt_str)
    catalog = EvidenceCatalogBuilder(_get_registry()).build(
        panel_id, df, decision_time
    )
    sample = [
        {
            "evidence_id": e.evidence_id,
            "symbol": e.symbol,
            "field_name": e.field_name,
            "value": e.value,
            "state": e.state.value,
            "age_hours": round(e.age_hours, 2),
            "semantic_caveat_zh": e.semantic_caveat_zh,
        }
        for e in catalog.evidence_catalog[:10]
    ]
    return EvidenceResponse(
        catalog_id=catalog.catalog_id,
        catalog_sha256=catalog.catalog_sha256,
        decision_time=catalog.decision_time.isoformat(),
        evidence_count=len(catalog.evidence_catalog),
        sample=sample,
    )


@router.post("")
def start_analysis(req: AnalysisRequest) -> dict:
    _manifest_path, manifest, df = _resolve_panel(req.panel_id)
    # CLI manifests use decision_time_utc; nested manifests use decision_time.
    default_dt_str = manifest.get("decision_time") or manifest["decision_time_utc"]
    decision_time = (
        datetime.fromisoformat(req.decision_time)
        if req.decision_time
        else datetime.fromisoformat(default_dt_str)
    )

    # Build evidence catalog
    catalog = EvidenceCatalogBuilder(_get_registry()).build(
        req.panel_id, df, decision_time
    )

    # Pick provider — match by enum *value* (lowercase string), not member name.
    try:
        provider = LLMProvider(req.provider)
    except ValueError:
        provider = LLMProvider.MOCK
    adapter = LLMAdapter(provider=provider, model=req.model)
    runner = AnalysisRunner(llm_adapter=adapter)
    result = runner.run(catalog, decision_time)
    return {
        "analysis_run_id": result.analysis_run_id,
        "status": result.status.value,
        "catalog_id": catalog.catalog_id,
        "catalog_sha256": catalog.catalog_sha256,
        "finding": (
            {
                "finding_id": result.finding.finding_id,
                "title_zh": result.finding.title_zh,
                "claim_zh": result.finding.claim_zh,
                "classification": result.finding.classification,
                "support_type": result.finding.support_type,
                "llm_confidence": result.finding.llm_confidence,
                "final_confidence": result.finding.final_confidence,
                "evidence_ids": result.finding.evidence_ids,
                "limitations_zh": result.finding.limitations_zh,
            }
            if result.finding
            else None
        ),
        "errors": result.errors,
    }


@router.get("/{analysis_run_id}/stream")
async def stream_analysis(
    analysis_run_id: str,
    request: Request,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
) -> StreamingResponse:
    async def event_gen() -> AsyncIterator[bytes]:
        start_idx = 0
        if last_event_id:
            try:
                _, idx = last_event_id.split(":")
                start_idx = int(idx) + 1
            except (ValueError, AttributeError):
                start_idx = 0
        events = get_run_events(analysis_run_id)
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
