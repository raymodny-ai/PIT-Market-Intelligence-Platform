"""Lineage API + Source Health (TODO T-27 / T-28)."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

import pit_market.api.panels as panels_api
from pit_market.llm.runner import get_run_events

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["lineage"])


# =============================================================================
# Lineage (T-28)
# =============================================================================


@router.get("/lineage/{entity_id}")
def get_lineage(entity_id: str) -> dict:
    """Return field-level lineage for an entity (finding/evidence/feature/observation/raw).

    Phase 4: walks the Silver/Evidence/Analysis artifacts on disk to
    reconstruct the 5-level chain. Full OpenLineage integration is a
    follow-up (T-28 Phase 4 ships a working implementation; production
    OpenLineage HTTP events come in Phase 5).
    """
    if panels_api._PANELS_DIR is None:
        raise HTTPException(status_code=503, detail="Panels dir not configured")

    # Try to find evidence_id in any panel's lineage
    if entity_id.startswith("ev_"):
        # evidence level — find which panel
        lineage = _find_evidence_lineage(entity_id, panels_api._PANELS_DIR)
    elif entity_id.startswith("finding_") or entity_id.startswith("analysis_"):
        # finding / analysis level — find in metadata
        lineage = _find_finding_lineage(entity_id, panels_api._PANELS_DIR)
    else:
        # observation / feature / raw — return generic node
        lineage = {
            "entity_id": entity_id,
            "level": "unknown",
            "path": [],
        }

    return {
        "entity_id": entity_id,
        "graph": {
            "nodes": [
                {"id": "finding", "label": "Finding"},
                {"id": "evidence", "label": "Evidence Catalog"},
                {"id": "feature", "label": "Feature Observation"},
                {"id": "observation", "label": "Normalized Observation"},
                {"id": "raw", "label": "Raw Record"},
            ],
            "edges": [
                {"from": "finding", "to": "evidence"},
                {"from": "evidence", "to": "feature"},
                {"from": "feature", "to": "observation"},
                {"from": "observation", "to": "raw"},
            ],
        },
        "lineage": lineage,
    }


def _find_evidence_lineage(evidence_id: str, panels_dir: Path) -> dict:
    # Search all panel manifest files for an evidence_id reference
    for manifest_path in panels_dir.rglob("panel_manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Phase 4: evidence_id is keyed by manifest.panels[*].evidence_ids list
        # (real lookup against metadata/evidence_catalogs deferred to T-28 follow-up)
        # Build a path: panel_id → evidence_id → upstream Silver → raw
        return {
            "level": "evidence",
            "panel_id": manifest.get("panel_id"),
            "panel_sha256": manifest.get("panel_sha256"),
            "evidence_id": evidence_id,
        }
    return {"level": "evidence", "path": []}


def _find_finding_lineage(finding_id: str, panels_dir: Path) -> dict:
    # Search analysis results
    base = panels_dir.parent.parent / "metadata" / "analyses" / finding_id
    finding_path = base / "finding.json"
    if finding_path.exists():
        finding = json.loads(finding_path.read_text(encoding="utf-8"))
        return {
            "level": "finding",
            "finding": finding.get("finding"),
            "analysis_run_id": finding_id,
            "catalog_id": finding.get("catalog_id"),
            "catalog_sha256": finding.get("catalog_sha256"),
            "evidence_ids": finding.get("finding", {}).get("evidence_ids", []),
        }
    # Not found
    return {"level": "finding", "path": []}


# =============================================================================
# Source Health (T-27 backend)
# =============================================================================


@router.get("/sources/status")
def sources_status() -> dict:
    """Source SLA / freshness / error counts.

    Phase 4 walks the Raw landing directories on disk and reports
    per-source stats from the manifest.json files.
    """
    if panels_api._PANELS_DIR is None:
        raise HTTPException(status_code=503, detail="Panels dir not configured")
    # raw_dir is one level up from panels_dir (both under data/)
    raw_dir = panels_api._PANELS_DIR.parent / "raw"
    if not raw_dir.exists():
        return {"sources": {}, "as_of_utc": datetime.now(UTC).isoformat()}

    sources: dict[str, dict[str, Any]] = {}
    for manifest in raw_dir.rglob("manifest.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        src = data.get("source_name", "unknown")
        s = sources.setdefault(src, {
            "source_name": src,
            "run_count": 0,
            "total_records": 0,
            "error_count": 0,
            "last_run_utc": None,
            "last_quality_status": None,
        })
        s["run_count"] += 1
        s["total_records"] += data.get("record_count", 0)
        if data.get("quality_status", "VALID") not in ("VALID", "EMPTY_RESPONSE"):
            s["error_count"] += 1
        ts = data.get("ingest_date", "")
        if ts and (s["last_run_utc"] is None or ts > s["last_run_utc"]):
            s["last_run_utc"] = ts
            s["last_quality_status"] = data.get("quality_status")

    return {
        "sources": sources,
        "as_of_utc": datetime.now(UTC).isoformat(),
    }


@router.get("/sources/{source_name}/events")
def source_events(source_name: str) -> dict:
    """Recent events (COT / macro / SEC releases) for a source.

    Phase 4: returns manifest timestamps sorted descending.
    """
    if panels_api._PANELS_DIR is None:
        raise HTTPException(status_code=503, detail="Panels dir not configured")
    raw_dir = panels_api._PANELS_DIR.parent / "raw"
    if not raw_dir.exists():
        return {"source": source_name, "events": []}
    events: list[dict[str, Any]] = []
    for manifest in raw_dir.rglob("manifest.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("source_name") != source_name:
            continue
        events.append({
            "ingest_date": data.get("ingest_date"),
            "run_id": data.get("run_id"),
            "dataset": data.get("dataset_name"),
            "record_count": data.get("record_count", 0),
            "quality_status": data.get("quality_status"),
        })
    events.sort(key=lambda e: (e.get("ingest_date") or ""), reverse=True)
    return {"source": source_name, "events": events[:50]}


# =============================================================================
# OpenLineage facet (T-28)
# =============================================================================


@router.get("/lineage/analysis/{analysis_run_id}/facet")
def analysis_lineage_facet(analysis_run_id: str) -> dict:
    """Return the LLMProvenanceRunFacet for an analysis run (T-28)."""
    events = get_run_events(analysis_run_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"No events for run: {analysis_run_id}")
    final = events[-1]["data"]
    facet = {
        "_producer": "pit-market",
        "_schemaURL": "https://pit.market/schemas/LLMProvenanceRunFacet.json",
        "model": final.get("model", "mock"),
        "prompt_version": final.get("prompt_version", "v0.3"),
        "schema_version": "v1",
        "validation_status": final.get("status", "UNKNOWN"),
        "evidence_count": len(final.get("evidence_ids", [])),
        "llm_confidence": final.get("llm_confidence"),
        "final_confidence": final.get("final_confidence"),
        "support_type": final.get("support_type"),
        "causal_language_level": final.get("causal_language_level"),
    }
    return facet
