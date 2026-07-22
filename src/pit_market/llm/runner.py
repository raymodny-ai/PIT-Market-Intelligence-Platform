"""LLM analysis runner with 5-stage SSE events (TODO T-23).

Pipeline:
QUEUED → EVIDENCE_READY → LLM_RUNNING → VALIDATING → PUBLISHED

(or → REJECTED at validation step)

Phase 3 ships the runner with a MockProvider. Real LLM Provider is wired
in T-21 follow-up.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pit_market.evidence.catalog import EvidenceCatalog
from pit_market.llm.adapter import LLMAdapter, LLMProvider
from pit_market.llm.validator import Finding, FindingValidator, ValidationStatus

log = logging.getLogger(__name__)


class AnalysisStatus(StrEnum):
    QUEUED = "QUEUED"
    EVIDENCE_READY = "EVIDENCE_READY"
    LLM_RUNNING = "LLM_RUNNING"
    VALIDATING = "VALIDATING"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


# In-memory run state (Phase 2: in-process; Phase 5: Redis stream)
_RUN_STATE: dict[str, list[dict[str, Any]]] = {}


class AnalysisRunResult:
    def __init__(
        self,
        analysis_run_id: str,
        status: AnalysisStatus,
        finding: Finding | None = None,
        errors: list[str] | None = None,
    ) -> None:
        self.analysis_run_id = analysis_run_id
        self.status = status
        self.finding = finding
        self.errors = errors or []


class AnalysisRunner:
    """5-stage pipeline."""

    def __init__(
        self,
        llm_adapter: LLMAdapter | None = None,
        validator: FindingValidator | None = None,
        runs_dir: str | Path = "./data/metadata/analyses",
    ) -> None:
        self._llm = llm_adapter or LLMAdapter(provider=LLMProvider.MOCK)
        self._validator = validator or FindingValidator()
        self._runs_dir = Path(runs_dir)

    def run(
        self,
        catalog: EvidenceCatalog,
        decision_time: datetime,
    ) -> AnalysisRunResult:
        """Synchronous run — pushes events to in-memory state and returns
        final result. For streaming, see ``stream_run``."""
        run_id = f"analysis_{uuid.uuid4().hex[:12]}"
        events: list[dict[str, Any]] = []

        def push(status: AnalysisStatus, pct: int, msg_zh: str) -> None:
            events.append({
                "event": "analysis_status",
                "id": f"{run_id}:{len(events)}",
                "data": {
                    "analysis_run_id": run_id,
                    "status": status.value,
                    "progress_pct": pct,
                    "message_zh": msg_zh,
                },
            })

        try:
            push(AnalysisStatus.QUEUED, 5, "排队中")
            push(AnalysisStatus.EVIDENCE_READY, 20, f"证据已就绪 ({len(catalog.evidence_catalog)} 条)")
            push(AnalysisStatus.LLM_RUNNING, 50, "LLM 分析中")
            raw = self._llm.analyze(catalog)
            push(AnalysisStatus.VALIDATING, 80, "校验证据引用、PIT 时间和数据质量")

            finding = Finding(
                finding_id=raw.get("finding_id", str(uuid.uuid4())),
                title_zh=raw["title_zh"],
                claim_zh=raw["claim_zh"],
                classification=raw["classification"],
                support_type=raw["support_type"],
                causal_language_level=raw["causal_language_level"],
                llm_confidence=raw["llm_confidence"],
                final_confidence=raw["llm_confidence"],  # adjusted by validator
                evidence_ids=raw["evidence_ids"],
                limitations_zh=raw["limitations_zh"],
                model=raw.get("model", "mock"),
                prompt_version=raw.get("prompt_version", "v0.3"),
            )

            result = self._validator.validate(finding, catalog, decision_time)
            if result.status == ValidationStatus.VALIDATED:
                push(AnalysisStatus.PUBLISHED, 100, "已发布")
                _RUN_STATE[run_id] = events
                self._persist(run_id, events, finding, decision_time, catalog)
                return AnalysisRunResult(run_id, AnalysisStatus.PUBLISHED, finding=finding)
            else:
                push(AnalysisStatus.REJECTED, 100, "校验失败")
                _RUN_STATE[run_id] = events
                return AnalysisRunResult(
                    run_id,
                    AnalysisStatus.REJECTED,
                    errors=result.errors,
                )
        except Exception as e:
            push(AnalysisStatus.FAILED, 100, f"失败: {e}")
            _RUN_STATE[run_id] = events
            return AnalysisRunResult(run_id, AnalysisStatus.FAILED, errors=[str(e)])

    async def stream_run(
        self,
        catalog: EvidenceCatalog,
        decision_time: datetime,
    ) -> AsyncIterator[dict[str, Any]]:
        """Async SSE-style iterator. Yields each event as it occurs."""
        # Phase 3: yields events in a tight loop. Real impl would integrate
        # with a worker queue (Celery / RQ / Dagster).
        result = await asyncio.to_thread(self.run, catalog, decision_time)
        for ev in _RUN_STATE.get(result.analysis_run_id, []):
            yield ev

    def _persist(
        self,
        run_id: str,
        events: list[dict[str, Any]],
        finding: Finding,
        decision_time: datetime,
        catalog: EvidenceCatalog,
    ) -> None:
        out_dir = self._runs_dir / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "events.json").write_text(
            json.dumps(events, indent=2, default=str), encoding="utf-8"
        )
        from dataclasses import asdict
        (out_dir / "finding.json").write_text(
            json.dumps({
                "analysis_run_id": run_id,
                "decision_time": decision_time.isoformat(),
                "catalog_id": catalog.catalog_id,
                "catalog_sha256": catalog.catalog_sha256,
                "finding": asdict(finding),
            }, indent=2, default=str),
            encoding="utf-8",
        )


def get_run_events(run_id: str) -> list[dict[str, Any]]:
    return _RUN_STATE.get(run_id, [])
