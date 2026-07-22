"""Notification subsystem — Feishu webhook (PRD T-31).

Posts a JSON card to a Feishu incoming webhook. The webhook URL is
read from ``PIT_MARKET_FEISHU_WEBHOOK``. When unset, calls are
recorded but not sent (no-op), so the system remains functional in
dev / CI environments.

The :class:`Notifier` exposes a typed surface for the three alert
classes from T-31:
  - source_sla: data source freshness / quality below threshold
  - quality_gate: pandera / Silver validation failure
  - panel_stale: a previously built panel is now stale
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class Alert:
    kind: str           # source_sla | quality_gate | panel_stale
    title: str
    summary_zh: str
    detail: dict[str, Any] = field(default_factory=dict)
    severity: str = "warning"  # info | warning | critical
    ts_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class Notifier:
    """Feishu webhook client with offline-safe send()."""

    def __init__(self, webhook_url: str | None = None, *, transport: Any | None = None) -> None:
        self._url = webhook_url or os.environ.get("PIT_MARKET_FEISHU_WEBHOOK", "")
        self._transport = transport  # callable(url, payload) for tests
        self._sent: list[Alert] = []   # always appended, even in no-op mode

    @property
    def sent(self) -> list[Alert]:
        return list(self._sent)

    def send(self, alert: Alert) -> bool:
        """Record ``alert`` and POST to Feishu if a URL is configured.

        Returns True if the alert was sent, False otherwise.
        """
        self._sent.append(alert)
        if not self._url and self._transport is None:
            return False
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": alert.title},
                    "template": (
                        "red" if alert.severity == "critical" else
                        "orange" if alert.severity == "warning" else "blue"
                    ),
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": alert.summary_zh,
                        },
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {"tag": "plain_text", "content": f"kind={alert.kind} ts={alert.ts_utc}"},
                        ],
                    },
                ],
            },
        }
        if self._transport is not None:
            self._transport(self._url, json.dumps(payload, ensure_ascii=False))
            return True
        try:
            import httpx
            httpx.post(self._url, json=payload, timeout=5.0)
            return True
        except Exception:
            return False

    # --- convenience constructors for the three PRD alert classes ---

    def source_sla(self, source: str, freshness_min: float, threshold_min: float) -> bool:
        return self.send(Alert(
            kind="source_sla",
            title=f"[PIT] {source} 数据陈旧",
            summary_zh=(
                f"源 `{source}` 当前新鲜度 {freshness_min:.0f} 分钟 "
                f"超过阈值 {threshold_min:.0f} 分钟"
            ),
            detail={"source": source, "freshness_min": freshness_min,
                    "threshold_min": threshold_min},
            severity="warning" if freshness_min < 2 * threshold_min else "critical",
        ))

    def quality_gate(self, dataset: str, rule: str, failed: int, total: int) -> bool:
        return self.send(Alert(
            kind="quality_gate",
            title=f"[PIT] {dataset} 质量门禁失败",
            summary_zh=(
                f"数据集 `{dataset}` 规则 `{rule}` 失败 {failed}/{total} 行"
            ),
            detail={"dataset": dataset, "rule": rule, "failed": failed, "total": total},
            severity="critical",
        ))

    def panel_stale(self, panel_id: str, age_min: float, threshold_min: float) -> bool:
        return self.send(Alert(
            kind="panel_stale",
            title=f"[PIT] Panel {panel_id} 已陈旧",
            summary_zh=(
                f"Panel `{panel_id}` 当前 age={age_min:.0f}min "
                f"超过阈值 {threshold_min:.0f}min"
            ),
            detail={"panel_id": panel_id, "age_min": age_min,
                    "threshold_min": threshold_min},
            severity="warning",
        ))
