"use client";

// LineageDrawer — 5-level Finding→Evidence→Feature→Obs→Raw tree
// (PRD §LineageDrawer). Each node shows key metadata (id, sha256, ts, …).

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useSelectionStore } from "../stores/selectionStore";
import { fetchLineage } from "../lib/api";
import { formatTimestamp, dataAgeHuman } from "../lib/formatting";
import type { LineageNode, LineageNodeKind } from "../types/api";

const LEVELS: LineageNodeKind[] = ["finding", "evidence", "feature", "observation", "raw"];

const LEVEL_LABEL: Record<LineageNodeKind, { zh: string; color: string; bg: string; icon: string }> = {
  finding:      { zh: "Finding",         color: "#4f46e5", bg: "bg-indigo-50",  icon: "F" },
  evidence:     { zh: "Evidence",        color: "#0ea5e9", bg: "bg-sky-50",     icon: "E" },
  feature:      { zh: "Feature",         color: "#10b981", bg: "bg-emerald-50", icon: "Ft" },
  observation:  { zh: "Observation",     color: "#a78bfa", bg: "bg-violet-50",  icon: "O" },
  raw:          { zh: "Raw Manifest",    color: "#f59e0b", bg: "bg-amber-50",   icon: "R" },
};

export interface LineageDrawerProps {
  onClose?: () => void;
  defaultEntityId?: string;
}

export function LineageDrawer({ onClose, defaultEntityId }: LineageDrawerProps) {
  const entityId = useSelectionStore((s) => s.openRawHash) ?? defaultEntityId ?? null;
  const closeAll = useSelectionStore((s) => s.clearAll);
  const setOpenRawHash = useSelectionStore((s) => s.setOpenRawHash);

  const query = useQuery({
    queryKey: ["lineage", entityId],
    queryFn: () => fetchLineage(entityId!),
    enabled: !!entityId,
    staleTime: 60_000,
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeAll(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeAll]);

  if (!entityId) return null;
  const graph = query.data;
  const byLevel: Record<LineageNodeKind, LineageNode[]> = {
    finding: [], evidence: [], feature: [], observation: [], raw: [],
  };
  for (const n of graph?.nodes ?? []) {
    byLevel[n.kind]?.push(n);
  }

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-ink-900/30"
        onClick={() => { setOpenRawHash(null); onClose?.(); }}
      />
      <div
        className="fixed right-0 top-0 z-50 h-full w-[480px] bg-white shadow-drawer flex flex-col"
        role="dialog"
      >
        <header className="px-4 py-3 border-b border-ink-200 flex items-center justify-between">
          <div>
            <div className="text-xs text-ink-500">5 级血缘</div>
            <div className="text-sm font-semibold text-ink-900 font-mono">{entityId}</div>
          </div>
          <button type="button" className="btn-icon" onClick={() => { setOpenRawHash(null); onClose?.(); }}>
            <CloseIcon />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {query.isLoading && <div className="skeleton h-40 w-full" />}
          {LEVELS.map((lvl, idx) => {
            const nodes = byLevel[lvl] ?? [];
            const meta = LEVEL_LABEL[lvl];
            return (
              <section key={lvl}>
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className={`w-7 h-7 rounded-full ${meta.bg} flex items-center justify-center text-xs font-bold`}
                    style={{ color: meta.color }}
                  >
                    {meta.icon}
                  </span>
                  <h3 className="text-sm font-semibold text-ink-900">{meta.zh}</h3>
                  <span className="text-xs text-ink-500">({nodes.length})</span>
                  {idx < LEVELS.length - 1 && (
                    <div className="flex-1 ml-1 border-t border-dashed border-ink-300" />
                  )}
                </div>
                {nodes.length === 0 ? (
                  <div className="text-xs text-ink-400 pl-9">无节点</div>
                ) : (
                  <ul className="space-y-1.5 pl-9">
                    {nodes.map((n) => (
                      <li key={n.id} className={`${meta.bg} rounded-md p-2 border`} style={{ borderColor: meta.color + "33" }}>
                        <div className="font-mono text-xs text-ink-900 truncate">{n.id}</div>
                        {n.label && <div className="text-xs text-ink-700">{n.label}</div>}
                        <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[10px] text-ink-500 mt-1">
                          {n.ts && <div>ts: {formatTimestamp(n.ts, false)}</div>}
                          {n.ts && <div>age: {dataAgeHuman(n.ts)}</div>}
                          {n.sha256 && <div className="col-span-2 font-mono truncate" title={n.sha256}>sha256: {n.sha256.slice(0, 16)}…</div>}
                          {n.url && (
                            <div className="col-span-2">
                              <a href={n.url} target="_blank" rel="noreferrer" className="text-brand-600 hover:underline truncate block">
                                {n.url}
                              </a>
                            </div>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
      </div>
    </>
  );
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M18 6L6 18M6 6l12 12" />
    </svg>
  );
}
