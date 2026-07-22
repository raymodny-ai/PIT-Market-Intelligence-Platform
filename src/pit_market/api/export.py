"""Slice export endpoints (T-18)."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime

import polars as pl
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

import pit_market.api.panels as panels_api
from pit_market.api.panels import SliceRequest
from pit_market.storage.cache import make_cache_key

log = logging.getLogger(__name__)

export_router = APIRouter(prefix="/v1/export", tags=["export"])


@export_router.post("/panels/{panel_id}")
def export_panel(panel_id: str, req: SliceRequest, format: str = "csv") -> Response:
    """Export a slice to CSV / Parquet / JSON.

    Format: csv | parquet | json
    Returns file with Content-Disposition + export manifest in headers.
    """
    if panels_api._PANELS_DIR is None:
        raise HTTPException(status_code=503, detail="Panels dir not configured")
    panel_path = next(panels_api._PANELS_DIR.rglob(f"{panel_id}/value_panel.parquet"), None)
    if panel_path is None:
        raise HTTPException(status_code=404, detail=f"Panel not found: {panel_id}")
    df = pl.read_parquet(str(panel_path))
    df = df.filter(pl.col("canonical_symbol").is_in(req.universe))
    if req.fields:
        df = df.filter(pl.col("field_name").is_in(req.fields))

    if df.is_empty():
        raise HTTPException(status_code=404, detail="Slice is empty")

    fmt = format.lower()
    now = datetime.now(UTC)
    export_id = f"export_{now.strftime('%Y%m%d%H%M%S')}_{hashlib.sha256(panel_id.encode()).hexdigest()[:6]}"
    slice_request_dict = req.model_dump(exclude_none=True)
    slice_request_sha256 = hashlib.sha256(
        json.dumps(slice_request_dict, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    data_response_sha256 = hashlib.sha256(
        df.write_json().encode("utf-8")
    ).hexdigest()

    if fmt == "csv":
        body = df.write_csv().encode("utf-8")
        media_type = "text/csv"
        filename = f"{export_id}.csv"
    elif fmt == "parquet":
        # Parquet is binary; write to a temp file then return as FileResponse
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
            df.write_parquet(tmp.name)
            parquet_path = tmp.name
        # Build manifest header
        manifest = {
            "export_id": export_id,
            "panel_id": panel_id,
            "slice_id": f"slice_{make_cache_key(panel_id, slice_request_dict)[:8]}",
            "slice_request_sha256": slice_request_sha256,
            "data_response_sha256": data_response_sha256,
            "report_version": "ui.v1.0",
            "created_at_utc": now.isoformat(),
        }
        return FileResponse(
            parquet_path,
            media_type="application/octet-stream",
            filename=f"{export_id}.parquet",
            headers={"X-Export-Manifest": json.dumps(manifest)},
        )
    elif fmt == "json":
        body = df.write_json().encode("utf-8")
        media_type = "application/json"
        filename = f"{export_id}.json"
    else:
        raise HTTPException(status_code=400, detail=f"unsupported format: {format!r}")

    manifest = {
        "export_id": export_id,
        "panel_id": panel_id,
        "slice_id": f"slice_{make_cache_key(panel_id, slice_request_dict)[:8]}",
        "slice_request_sha256": slice_request_sha256,
        "data_response_sha256": data_response_sha256,
        "report_version": "ui.v1.0",
        "created_at_utc": now.isoformat(),
    }
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Manifest": json.dumps(manifest),
        },
    )
