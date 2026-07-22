"use client";

// PITContextBar — sticky top context (PRD §PITContextBar).
// Shows: panel_id, decision_time, panel_version, feature_version,
//        quality badge, data_age, "另存为快照" button.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSliceStore } from "../stores/sliceStore";
import { useReportStore } from "../stores/reportStore";
import { PanelSwitcher } from "./PanelSwitcher";
import { useMounted } from "../lib/useMounted";
import { formatTimestamp, dataAgeHuman, qualityPill } from "../lib/formatting";
import type { QualityStatus } from "../types/api";

export interface PITContextBarProps {
  panelId?: string;
  decisionTime?: string;
  panelVersion?: string;
  featureVersion?: string;
  qualityStatus?: QualityStatus;
  dataAgeHours?: number;
  onSaveSnapshot?: () => void;
  onTimeClick?: () => void;
}

export function PITContextBar(props: PITContextBarProps) {
  const slice = useSliceStore();
  const currentRun = useReportStore((s) => s.currentRun);
  const [hovered, setHovered] = useState(false);
  const mounted = useMounted();

  // Refresh the store's sentinel decisionTime / dateRange to real "now"
  // once the component has mounted. SSR uses the sentinel so it matches
  // the first client render; this effect then updates to the real values.
  useEffect(() => {
    if (!mounted) return;
    if (slice.decisionTime === "1970-01-01T00:00:00.000Z") {
      slice.setDecisionTime(new Date().toISOString());
    }
    if (slice.dateRange.end === "1970-01-01") {
      const end = new Date().toISOString().slice(0, 10);
      const start = new Date(Date.now() - 90 * 24 * 3600 * 1000).toISOString().slice(0, 10);
      slice.setDateRange({ start, end });
    }
  }, [mounted, slice]);

  const panelId = props.panelId ?? slice.panelId ?? "latest";
  const decisionTime = props.decisionTime ?? slice.decisionTime;
  const panelVersion = props.panelVersion ?? "—";
  const featureVersion = props.featureVersion ?? "—";
  const quality = props.qualityStatus ?? "VALID";
  const pill = qualityPill(quality);
  // dataAgeHuman depends on Date.now() which differs between server render
  // and client hydration, so only render it after the component mounts.
  // Server shows "—" so SSR HTML matches the first client render.
  const dataAgeStr = !mounted
    ? "—"
    : props.dataAgeHours !== undefined
    ? dataAgeHuman(new Date(Date.now() - props.dataAgeHours * 3600 * 1000).toISOString())
    : dataAgeHuman(decisionTime);

  return (
    <div
      className="sticky top-0 z-30 w-full bg-white border-b border-ink-200 shadow-sm"
      onMouseLeave={() => setHovered(false)}
    >
      <div className="flex items-center gap-3 px-4 py-2 text-sm">
        <div className="flex items-center gap-2 min-w-0">
          <span className="label-muted">Panel</span>
          <span className="font-mono text-ink-900 truncate max-w-[180px]" title={panelId}>
            {panelId}
          </span>
        </div>

        <div className="h-4 w-px bg-ink-200" />

        <button
          type="button"
          onClick={props.onTimeClick}
          onMouseEnter={() => setHovered(true)}
          className="flex items-center gap-2 hover:bg-ink-50 rounded px-1.5 py-0.5 transition-colors"
          title="点击打开时间回放"
        >
          <span className="label-muted">decision_time</span>
          <span className={`font-mono tabular-nums ${hovered ? "text-brand-600" : "text-ink-900"}`}>
            {formatTimestamp(decisionTime, false)}
          </span>
          <span className="text-ink-500 text-xs">({slice.decisionClock})</span>
        </button>

        <div className="h-4 w-px bg-ink-200" />

        <div className="flex items-center gap-2 min-w-0">
          <span className="label-muted">panel_version</span>
          <span className="font-mono text-ink-700">{panelVersion}</span>
        </div>

        <div className="flex items-center gap-2 min-w-0">
          <span className="label-muted">feature_version</span>
          <span className="font-mono text-ink-700">{featureVersion}</span>
        </div>

        <div className="flex-1" />

        <div className="flex items-center gap-2">
          <span className="label-muted">quality</span>
          <span className={pill.className}>
            <span className={`pulse-dot ${pill.dotClass}`} />
            {pill.label}
          </span>
        </div>

        <div className="h-4 w-px bg-ink-200" />

        <div className="flex items-center gap-2">
          <span className="label-muted">data_age</span>
          <span className="text-ink-900 tabular-nums">{dataAgeStr}</span>
        </div>

        {currentRun && (
          <>
            <div className="h-4 w-px bg-ink-200" />
            <div className="flex items-center gap-2">
              <span className="label-muted">run</span>
              <span className="font-mono text-ink-700">{currentRun.run_id.slice(0, 8)}</span>
              <span className="text-xs text-brand-600">{currentRun.stage}</span>
            </div>
          </>
        )}

        <PanelSwitcher currentPanelId={panelId} className="ml-2" />

        <Link
          href="/panels/new"
          className="ml-1 flex items-center gap-1 rounded border border-brand-500 bg-white px-2 py-1 text-sm text-brand-700 hover:bg-brand-50 transition-colors"
          title="新建 PIT panel"
        >
          <PlusIcon /> 新建
        </Link>

        <button
          type="button"
          onClick={props.onSaveSnapshot}
          className="btn-ghost ml-1"
        >
          <SaveIcon /> 另存为快照
        </button>
      </div>
    </div>
  );
}

function SaveIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
      <polyline points="17 21 17 13 7 13 7 21" />
      <polyline points="7 3 7 8 15 8" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}
