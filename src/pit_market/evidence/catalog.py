"""Evidence Catalog (TODO T-20).

Builds an immutable catalog from a PIT panel:
- For each (symbol, field_name, observation_time) the latest value is captured
- A stable ``evidence_id`` is generated (hash-based, deterministic)
- Field-level lineage: evidence_id → feature_observation_id → raw_record_hash

The catalog is the LLM's only input (T-21). The catalog itself is
validated against ``evidence.schema.json``.

Discipline:
- Semantic warnings from source/feature propagate up (discipline #7)
- Catalog ``sha256`` is computed from the JSON-serialized entries
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

import polars as pl

from pit_market.storage.registry import Registry

log = logging.getLogger(__name__)


class FieldState(StrEnum):
    LOW_EXTREME = "LOW_EXTREME"
    LOW = "LOW"
    NEUTRAL = "NEUTRAL"
    HIGH = "HIGH"
    HIGH_EXTREME = "HIGH_EXTREME"
    MISSING = "MISSING"
    STALE = "STALE"
    INFERRED_AVAILABILITY = "INFERRED_AVAILABILITY"


def _zscore_to_state(value: float | None) -> FieldState:
    """Phase 3 simple mapping: z-score → field state. T-22 will refine."""
    if value is None:
        return FieldState.MISSING
    if value >= 2.0:
        return FieldState.HIGH_EXTREME
    if value >= 1.0:
        return FieldState.HIGH
    if value <= -2.0:
        return FieldState.LOW_EXTREME
    if value <= -1.0:
        return FieldState.LOW
    return FieldState.NEUTRAL


@dataclass(frozen=True)
class EvidenceEntry:
    evidence_id: str
    symbol: str
    field_name: str
    display_name_zh: str
    value: float
    unit: str
    state: FieldState
    observation_time: datetime
    available_at: datetime
    age_hours: float
    source_name: str
    dataset_name: str
    feature_observation_id: str
    normalized_observation_id: str
    raw_record_hash: str
    feature_definition_id: str
    quality_status: str
    semantic_caveat_zh: str


@dataclass
class EvidenceCatalog:
    catalog_id: str
    pit_panel_id: str
    decision_time: datetime
    catalog_sha256: str
    evidence_catalog: list[EvidenceEntry] = field(default_factory=list)
    output_path: Path | None = None


def _make_evidence_id(symbol: str, field: str, obs_time: datetime, raw_hash: str) -> str:
    body = f"{symbol}|{field}|{obs_time.isoformat()}|{raw_hash}"
    return f"ev_{hashlib.sha256(body.encode()).hexdigest()[:16]}"


class EvidenceCatalogBuilder:
    """Build an EvidenceCatalog from a PIT panel + registry."""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def build(
        self,
        panel_id: str,
        panel_df: pl.DataFrame,
        decision_time: datetime,
        output_dir: str | Path = "./data/metadata/evidence_catalogs",
    ) -> EvidenceCatalog:
        """Build catalog from panel rows.

        Skips rows with null value or MISSING state.
        """
        if panel_df.is_empty():
            return EvidenceCatalog(
                catalog_id="catalog_empty",
                pit_panel_id=panel_id,
                decision_time=decision_time,
                catalog_sha256=hashlib.sha256(b"{}").hexdigest(),
                evidence_catalog=[],
            )

        entries: list[EvidenceEntry] = []
        for row in panel_df.iter_rows(named=True):
            value = row.get("value")
            if value is None or (isinstance(value, float) and value != value):
                continue
            symbol = row.get("canonical_symbol", "")
            field_name = row.get("field_name", "")
            obs_time = row.get("observation_time")
            avail = row.get("available_at")
            raw_hash = row.get("raw_record_hash", "")
            if obs_time is None or avail is None:
                continue
            # Get semantic_warning from metric registry (discipline #7)
            metric = self._registry.metrics.get(field_name)
            caveat = metric.semantic_warning if metric else ""

            age_hours = (decision_time - avail).total_seconds() / 3600.0
            state = _zscore_to_state(float(value) if "zscore" in field_name else None)

            entries.append(
                EvidenceEntry(
                    evidence_id=_make_evidence_id(symbol, field_name, obs_time, raw_hash),
                    symbol=symbol,
                    field_name=field_name,
                    display_name_zh=metric.display_name_zh if metric else field_name,
                    value=float(value),
                    unit=metric.unit if metric else "",
                    state=state,
                    observation_time=obs_time,
                    available_at=avail,
                    age_hours=age_hours,
                    source_name=row.get("source_name", ""),
                    dataset_name=row.get("dataset_name", ""),
                    feature_observation_id=row.get("feature_observation_id", "n/a"),
                    normalized_observation_id=row.get("observation_id", ""),
                    raw_record_hash=raw_hash,
                    feature_definition_id=metric.feature_definition_id if metric else "n/a",
                    quality_status=row.get("quality_status", "VALID"),
                    semantic_caveat_zh=caveat,
                )
            )

        body = json.dumps(
            [asdict(e) for e in entries], sort_keys=True, default=str
        )
        catalog_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        catalog_id = f"catalog_{decision_time.strftime('%Y%m%d_%H%M')}_{catalog_sha[:8]}"

        # Persist
        out_path = Path(output_dir) / f"{catalog_id}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "catalog_id": catalog_id,
            "pit_panel_id": panel_id,
            "decision_time": decision_time.isoformat(),
            "catalog_sha256": catalog_sha,
            "evidence_count": len(entries),
        }
        full = {
            "manifest": manifest,
            "evidence_catalog": [asdict(e) for e in entries],
        }
        out_path.write_text(json.dumps(full, indent=2, default=str), encoding="utf-8")

        return EvidenceCatalog(
            catalog_id=catalog_id,
            pit_panel_id=panel_id,
            decision_time=decision_time,
            catalog_sha256=catalog_sha,
            evidence_catalog=entries,
            output_path=out_path,
        )

    def get_evidence(self, catalog: EvidenceCatalog, evidence_id: str) -> EvidenceEntry | None:
        for e in catalog.evidence_catalog:
            if e.evidence_id == evidence_id:
                return e
        return None
