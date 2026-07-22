"""Analyses API: LLM finding creation + SSE (TODO T-20 / T-23)."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
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
    if panels_api._PANELS_DIR is None:
        raise HTTPException(status_code=503, detail="Panels dir not configured")
    panel_path = next(panels_api._PANELS_DIR.rglob(f"{panel_id}/value_panel.parquet"), None)
    if panel_path is None:
        raise HTTPException(status_code=404, detail=f"Panel not found: {panel_id}")
    df = pl.read_parquet(str(panel_path))
    manifest_path = panel_path.parent / "panel_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    decision_time = datetime.fromisoformat(manifest["decision_time"])
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
    if panels_api._PANELS_DIR is None:
        raise HTTPException(status_code=503, detail="Panels dir not configured")
    panel_path = next(panels_api._PANELS_DIR.rglob(f"{req.panel_id}/value_panel.parquet"), None)
    if panel_path is None:
        raise HTTPException(status_code=404, detail=f"Panel not found: {req.panel_id}")
    df = pl.read_parquet(str(panel_path))
    manifest_path = panel_path.parent / "panel_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    decision_time = (
        datetime.fromisoformat(req.decision_time)
        if req.decision_time
        else datetime.fromisoformat(manifest["decision_time"])
    )

    # Build evidence catalog
    catalog = EvidenceCatalogBuilder(_get_registry()).build(
        req.panel_id, df, decision_time
    )

    # Pick provider
    provider = LLMProvider(req.provider) if req.provider in LLMProvider.__members__ else LLMProvider.MOCK
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
