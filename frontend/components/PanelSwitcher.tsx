"use client";

// PanelSwitcher — top-right dropdown to jump between built panels.
//
// Loads the manifest list via /v1/panels (newest first), shows a compact
// popover with panel_id · decision_time · universe, and navigates to
// /panels/{panel_id} on selection. From there, app/panels/[panelId]/page.tsx
// calls slice.setPanelId(panelId) so the global store stays in sync.
//
// Behaviour:
//   - "latest" sentinel is shown as a synthetic first entry ("latest (auto)")
//   - selecting "latest" navigates to /panels/latest, which resolves to the
//     newest manifest server-side via /v1/panels/latest
//   - closes on outside click and Escape; arrow keys cycle the list

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { fetchPanelsList } from "../lib/api";
import { formatTimestampUtc } from "../lib/formatting";
import type { PanelListEntry } from "../types/api";

export interface PanelSwitcherProps {
  currentPanelId: string;
  className?: string;
}

export function PanelSwitcher({ currentPanelId, className = "" }: PanelSwitcherProps) {
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [highlight, setHighlight] = useState(0);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const listQ = useQuery({
    queryKey: ["panels-list"],
    queryFn: () => fetchPanelsList(),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  const panels: PanelListEntry[] = listQ.data?.panels ?? [];

  const items = useMemo(() => {
    // Prepend a synthetic "latest" entry so users can always return to the
    // newest panel without picking a specific one.
    const synth: PanelListEntry = {
      panel_id: "latest",
    };
    return [synth, ...panels];
  }, [panels]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return items;
    return items.filter((p) => {
      const hay = `${p.panel_id} ${p.decision_time_utc ?? ""} ${(p.universe ?? []).join(" ")}`.toLowerCase();
      return hay.includes(q);
    });
  }, [items, filter]);

  // Close on outside click + Escape.
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((h) => Math.min(h + 1, Math.max(filtered.length - 1, 0)));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((h) => Math.max(h - 1, 0));
      } else if (e.key === "Enter" && filtered[highlight]) {
        e.preventDefault();
        choose(filtered[highlight]);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, filtered, highlight]);

  // Reset highlight when filter changes.
  useEffect(() => {
    setHighlight(0);
  }, [filter]);

  // Auto-focus the search input when opened.
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  function choose(p: PanelListEntry) {
    setOpen(false);
    setFilter("");
    // Always navigate to /panels/{id} — that page calls slice.setPanelId(),
    // keeping URL ↔ store in sync. For "latest" we go to /panels/latest
    // which still resolves via /v1/panels/latest server-side.
    const target = p.panel_id === "latest" ? "/panels/latest" : `/panels/${encodeURIComponent(p.panel_id)}`;
    router.push(target);
  }

  const currentLabel = currentPanelId && currentPanelId !== "latest" ? currentPanelId : "latest (auto)";
  const count = listQ.data?.count ?? 0;

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded border border-ink-200 bg-white px-2 py-1 text-sm font-mono text-ink-900 hover:bg-ink-50 hover:border-brand-400 transition-colors"
        title={`切换 panel_id (${count} 个已建)`}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <SwitchIcon />
        <span className="max-w-[180px] truncate">{currentLabel}</span>
        <span className="text-ink-400 text-xs">({count})</span>
        <Chevron open={open} />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-50 w-[420px] rounded-lg border border-ink-200 bg-white shadow-lg"
          role="listbox"
        >
          <div className="p-2 border-b border-ink-100">
            <input
              ref={inputRef}
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="搜索 panel_id / decision_time / 标的…"
              className="w-full rounded border border-ink-200 px-2 py-1 text-sm focus:outline-none focus:border-brand-400"
            />
          </div>

          <div className="max-h-[360px] overflow-y-auto">
            {listQ.isLoading && (
              <div className="px-3 py-4 text-sm text-ink-500">加载中…</div>
            )}
            {listQ.isError && (
              <div className="px-3 py-4 text-sm text-red-600">
                无法连接后端 /v1/panels ({listQ.error?.message ?? "unknown"})
              </div>
            )}
            {!listQ.isLoading && !listQ.isError && filtered.length === 0 && (
              <div className="px-3 py-4 text-sm text-ink-500">无匹配 panel</div>
            )}

            {filtered.map((p, i) => {
              const isCurrent = p.panel_id === currentPanelId;
              const isHighlight = i === highlight;
              return (
                <button
                  key={p.panel_id}
                  type="button"
                  onClick={() => choose(p)}
                  onMouseEnter={() => setHighlight(i)}
                  className={`w-full text-left px-3 py-2 border-l-2 transition-colors ${
                    isHighlight
                      ? "bg-brand-50 border-brand-500"
                      : "border-transparent hover:bg-ink-50"
                  } ${isCurrent ? "font-semibold" : ""}`}
                  role="option"
                  aria-selected={isCurrent}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-ink-900 truncate">
                      {p.panel_id === "latest" ? "latest (auto)" : p.panel_id}
                    </span>
                    {isCurrent && (
                      <span className="rounded bg-brand-100 px-1.5 py-0.5 text-[10px] font-medium text-brand-700">
                        CURRENT
                      </span>
                    )}
                    {p.panel_id !== "latest" && p._mtime_utc && (
                      <span className="ml-auto text-[10px] text-ink-400 font-mono">
                        {formatTimestampUtc(p._mtime_utc)}
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs text-ink-500 truncate">
                    {p.decision_time_utc ? (
                      <>
                        <span className="font-mono">{p.decision_time_utc}</span>
                        {" · "}
                        <span>{p.decision_clock ?? "1805_ET"}</span>
                        {p.universe && p.universe.length > 0 && (
                          <>
                            {" · "}
                            <span>universe: {p.universe.join(", ")}</span>
                          </>
                        )}
                      </>
                    ) : (
                      <span>最近一次构建的 panel(后端按 mtime 选)</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          <div className="border-t border-ink-100 px-3 py-1.5 text-[10px] text-ink-400 flex justify-between">
            <span>↑↓ 选择 · Enter 确认 · Esc 关闭</span>
            <span>{filtered.length} / {items.length}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function SwitchIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="17 1 21 5 17 9" />
      <path d="M3 11V9a4 4 0 0 1 4-4h14" />
      <polyline points="7 23 3 19 7 15" />
      <path d="M21 13v2a4 4 0 0 1-4 4H3" />
    </svg>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`transition-transform ${open ? "rotate-180" : ""}`}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}