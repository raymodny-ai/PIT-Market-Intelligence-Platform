"use client";

// EvidenceDrawer — 480px slide-over (PRD §EvidenceDrawer).
// Triggered by FindingCard click, AG Grid context menu, chart point click.

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useSelectionStore } from "../stores/selectionStore";
import { fetchEvidence } from "../lib/api";
import { dataAgeHuman, formatNumber, formatTimestamp, qualityPill } from "../lib/formatting";
import type { Evidence } from "../types/api";

export interface EvidenceDrawerProps {
  panelId: string;
  onClose?: () => void;
  onLineageClick?: (e: Evidence) => void;
}

export function EvidenceDrawer({ panelId, onClose, onLineageClick }: EvidenceDrawerProps) {
  const evidenceIds = useSelectionStore((s) => s.openEvidenceIds);
  const closeEvidence = useSelectionStore((s) => s.closeEvidence);
  const setOpenRawHash = useSelectionStore((s) => s.setOpenRawHash);

  // We need to refetch the whole evidence list and find the matching ids
  const query = useQuery({
    queryKey: ["evidence", panelId],
    queryFn: () => fetchEvidence(panelId),
    enabled: !!panelId && panelId !== "latest" && evidenceIds.length > 0,
    staleTime: 30_000,
  });

  const allEvidence = query.data?.evidence ?? [];
  const active = evidenceIds
    .map((id) => allEvidence.find((e) => e.evidence_id === id))
    .filter(Boolean) as Evidence[];

  // Close on ESC
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeEvidence(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeEvidence]);

  if (evidenceIds.length === 0) return null;

  const staleCount = active.filter((e) => e.quality_status === "STALE" || e.quality_status === "DEGRADED").length;
  const inferredCount = active.filter((e) => e.quality_status === "INFERRED_AVAILABILITY").length;
  const maxStale = active.reduce((m, e) => Math.max(m, e.data_age_days ?? 0), 0);

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-ink-900/30"
        onClick={() => { closeEvidence(); onClose?.(); }}
      />
      <div
        className="fixed right-0 top-0 z-50 h-full w-[480px] bg-white shadow-drawer flex flex-col"
        role="dialog"
      >
        <header className="px-4 py-3 border-b border-ink-200 flex items-center justify-between">
          <div>
            <div className="text-xs text-ink-500">证据详情</div>
            <div className="text-sm font-semibold text-ink-900">
              {active.length} 条证据 · Panel {panelId}
            </div>
          </div>
          <button type="button" className="btn-icon" onClick={() => { closeEvidence(); onClose?.(); }} aria-label="关闭">
            <CloseIcon />
          </button>
        </header>

        {(staleCount > 0 || inferredCount > 0) && (
          <div className="px-4 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber-800">
            ⚠️ 共 {staleCount + inferredCount} 条证据非最优质量
            {maxStale > 0 && <span className="ml-1">(最大陈旧 {maxStale} 天)</span>}
            <span className="block">后端已将 final_confidence 自动降级,此处仅展示。</span>
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          {query.isLoading && (
            <div className="p-4 space-y-2">
              <div className="skeleton h-16 w-full" />
              <div className="skeleton h-16 w-full" />
              <div className="skeleton h-16 w-full" />
            </div>
          )}
          {active.map((e) => {
            const pill = qualityPill(e.quality_status);
            return (
              <article key={e.evidence_id} className="px-4 py-3 border-b border-ink-200 hover:bg-ink-50">
                <div className="flex items-start justify-between mb-1.5">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-mono text-ink-900 truncate">{e.field_name}</div>
                    <div className="text-xs text-ink-500 truncate">{e.display_name_zh ?? e.source_name}</div>
                  </div>
                  <span className={pill.className}>
                    <span className={`pulse-dot ${pill.dotClass}`} />
                    {pill.label}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-1 text-xs text-ink-700 mb-1">
                  <div>当前值: <span className="font-mono tabular-nums text-ink-900">{formatNumber(e.value)}</span> {e.unit}</div>
                  <div>数据年龄: <span className="tabular-nums">{dataAgeHuman(e.available_at)}</span></div>
                  <div>observation_time: <span className="font-mono">{formatTimestamp(e.observation_time, false)}</span></div>
                  <div>available_at: <span className="font-mono">{formatTimestamp(e.available_at, false)}</span></div>
                </div>
                {e.semantic_caveat_zh && (
                  <div className="text-xs bg-amber-50 border border-amber-200 rounded px-2 py-1 mt-1 text-amber-800">
                    ⚠️ {e.semantic_caveat_zh}
                  </div>
                )}
                <div className="flex items-center gap-1 mt-2">
                  <button
                    type="button"
                    className="btn-ghost text-xs"
                    onClick={() => onLineageClick?.(e)}
                  >
                    查看完整血缘
                  </button>
                  <button
                    type="button"
                    className="btn-ghost text-xs"
                    onClick={() => setOpenRawHash(e.raw_record_hash ?? null)}
                    disabled={!e.raw_record_hash}
                  >
                    查看 Raw manifest
                  </button>
                </div>
              </article>
            );
          })}
        </div>

        <footer className="px-4 py-3 border-t border-ink-200 flex justify-end gap-2">
          <button type="button" className="btn-ghost text-xs" onClick={() => exportJson(active)}>
            导出 JSON
          </button>
          <button type="button" className="btn-ghost text-xs" onClick={() => { closeEvidence(); onClose?.(); }}>
            关闭
          </button>
        </footer>
      </div>
    </>
  );
}

function exportJson(evidence: Evidence[]) {
  const blob = new Blob([JSON.stringify(evidence, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `evidence-${new Date().toISOString().slice(0, 19)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M18 6L6 18M6 6l12 12" />
    </svg>
  );
}
