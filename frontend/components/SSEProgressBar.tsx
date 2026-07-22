"use client";

// SSEProgressBar — 5-stage analysis progress (PRD §SSEProgressBar).
// Listens to /v1/analyses/{id}/stream via useSSEStream hook; auto-reconnect
// with exp backoff (max 3 retries). Shown as a sticky toast in bottom-right.

import { useEffect } from "react";
import { useReportStore } from "../stores/reportStore";
import { useSSEStream } from "../lib/useSSEStream";
import type { AnalysisStage } from "../types/api";

const STAGE_ORDER: AnalysisStage[] = ["QUEUED", "EVIDENCE_READY", "LLM_RUNNING", "VALIDATING", "PUBLISHED"];
const STAGE_LABEL: Record<AnalysisStage, string> = {
  QUEUED: "排队",
  EVIDENCE_READY: "证据就绪",
  LLM_RUNNING: "LLM 推理",
  VALIDATING: "校验",
  PUBLISHED: "已发布",
  REJECTED: "已拒绝",
};

const STAGE_COLOR: Record<AnalysisStage, string> = {
  QUEUED: "bg-ink-300",
  EVIDENCE_READY: "bg-sky-500",
  LLM_RUNNING: "bg-sky-500 animate-pulse",
  VALIDATING: "bg-amber-500",
  PUBLISHED: "bg-emerald-500",
  REJECTED: "bg-rose-500",
};

export function SSEProgressBar() {
  const run = useReportStore((s) => s.currentRun);
  const updateStage = useReportStore((s) => s.updateRunStage);
  const finishRun = useReportStore((s) => s.finishRun);
  const failRun = useReportStore((s) => s.failRun);
  const recordReconnect = useReportStore((s) => s.recordReconnect);
  const reconnectAttempts = useReportStore((s) => s.reconnectAttempts);

  const url = run ? `${process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000"}/v1/analyses/${run.run_id}/stream` : "";
  const { status, retryCount } = useSSEStream({
    url,
    enabled: !!run && run.stage !== "PUBLISHED" && run.stage !== "REJECTED",
    onMessage: (msg) => {
      const stage = (msg.data?.stage ?? msg.data?.status) as AnalysisStage | undefined;
      if (stage) {
        const progress = typeof msg.data?.progress_pct === "number" ? msg.data.progress_pct : undefined;
        updateStage(stage, progress ?? run?.progress_pct ?? 0, {
          evidence_count: msg.data?.evidence_count,
          model: msg.data?.model,
        });
        if (stage === "PUBLISHED") {
          finishRun(msg.data?.finding_count ?? 0);
        } else if (stage === "REJECTED") {
          failRun(msg.data?.reason ?? "validation failed");
        }
      } else if (msg.data?.finding_count !== undefined) {
        finishRun(msg.data.finding_count);
      }
    },
    onError: () => { recordReconnect(); },
    onComplete: () => { /* final state held in store */ },
  });

  if (!run) return null;
  const idxCurrent = STAGE_ORDER.indexOf(run.stage as AnalysisStage);
  const isRejected = run.stage === "REJECTED";

  return (
    <div className="fixed bottom-4 right-4 z-50 w-[360px] card shadow-drawer">
      <header className="px-4 py-2 border-b border-ink-200 flex items-center justify-between">
        <div>
          <div className="text-xs text-ink-500">LLM 分析进度</div>
          <div className="text-sm font-mono text-ink-900 truncate max-w-[220px]" title={run.run_id}>{run.run_id}</div>
        </div>
        <span className={`quality-pill ${STAGE_COLOR[run.stage as AnalysisStage] ?? "bg-ink-200"} text-white`}>
          {STAGE_LABEL[run.stage as AnalysisStage] ?? run.stage}
        </span>
      </header>

      <div className="px-4 py-3">
        <div className="flex items-center gap-1 mb-2">
          {STAGE_ORDER.map((s, i) => {
            const reached = i <= idxCurrent && !isRejected;
            const current = i === idxCurrent && !isRejected;
            return (
              <div key={s} className="flex-1 flex items-center">
                <div
                  className={`h-1.5 flex-1 rounded-full ${
                    current ? STAGE_COLOR[s] :
                    reached ? "bg-emerald-500" : "bg-ink-200"
                  }`}
                />
              </div>
            );
          })}
        </div>
        <div className="grid grid-cols-5 text-[10px] text-ink-500 -mx-1">
          {STAGE_ORDER.map((s, i) => (
            <div key={s} className={`px-1 text-center ${i === idxCurrent ? "text-ink-900 font-medium" : ""}`}>
              {STAGE_LABEL[s]}
            </div>
          ))}
        </div>

        <div className="mt-3 text-xs text-ink-500 space-y-0.5">
          <div>panel: <span className="font-mono text-ink-900">{run.panel_id}</span></div>
          {run.evidence_count !== undefined && <div>evidence: <span className="tabular-nums text-ink-900">{run.evidence_count}</span></div>}
          {run.model && <div>model: <span className="font-mono text-ink-900">{run.model}</span></div>}
          {run.finding_count !== undefined && <div>findings: <span className="tabular-nums text-ink-900">{run.finding_count}</span></div>}
          {run.error && <div className="text-rose-700">error: {run.error}</div>}
        </div>

        {status === "error" && retryCount > 0 && (
          <div className="mt-2 text-xs text-amber-700">
            ⚠️ 连接中断,正在重连({retryCount}/3)…
          </div>
        )}
        {reconnectAttempts > 0 && status === "open" && (
          <div className="mt-2 text-xs text-emerald-700">
            ✓ 已从断点恢复(reconnect #{reconnectAttempts})
          </div>
        )}
      </div>
    </div>
  );
}
