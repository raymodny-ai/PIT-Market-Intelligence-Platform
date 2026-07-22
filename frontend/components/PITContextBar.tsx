"use client";

// PITContextBar — sticky top context (PRD §PITContextBar).
// Shows: panel_id, decision_time, panel_version, feature_version,
//        quality badge, data_age, "另存为快照" button.

import { useState } from "react";
import { useSliceStore } from "../stores/sliceStore";
import { useReportStore } from "../stores/reportStore";
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

  const panelId = props.panelId ?? slice.panelId ?? "latest";
  const decisionTime = props.decisionTime ?? slice.decisionTime;
  const panelVersion = props.panelVersion ?? "—";
  const featureVersion = props.featureVersion ?? "—";
  const quality = props.qualityStatus ?? "VALID";
  const pill = qualityPill(quality);
  const dataAgeStr = props.dataAgeHours !== undefined
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

        <button
          type="button"
          onClick={props.onSaveSnapshot}
          className="btn-ghost ml-2"
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
