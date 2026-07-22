"use client";

// RevisionTimeline — ALFRED vintage comparison (PRD §RevisionTimeline).
// Toggle as-known vs latest; red overlay shows the delta; click revision
// event opens EvidenceDrawer.

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { useSelectionStore } from "../stores/selectionStore";
import { formatTimestamp } from "../lib/formatting";
import type { RevisionTimeline as RT } from "../types/api";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

export interface RevisionTimelineProps {
  data: RT;
  height?: number;
}

export function RevisionTimeline({ data, height = 360 }: RevisionTimelineProps) {
  const [mode, setMode] = useState<"as_known" | "latest" | "diff">("as_known");
  const openEvidence = useSelectionStore((s) => s.openEvidence);

  const traces = useMemo(() => {
    const out: any[] = [];
    if (mode === "as_known" || mode === "diff") {
      out.push({
        type: "scatter", mode: "lines", name: "as-known (历史发布值)",
        x: data.as_known_series.map((p) => p.ts),
        y: data.as_known_series.map((p) => p.v),
        line: { color: "#4f46e5", width: 1.5 },
      });
    }
    if (mode === "latest" || mode === "diff") {
      out.push({
        type: "scatter", mode: "lines", name: "latest (最新修订值)",
        x: data.latest_series.map((p) => p.ts),
        y: data.latest_series.map((p) => p.v),
        line: { color: "#10b981", width: 1.5, dash: "dot" },
      });
    }
    if (mode === "diff") {
      out.push({
        type: "scatter", mode: "lines", name: "delta (latest − as_known)",
        x: data.events.map((e) => e.ts_utc),
        y: data.events.map((e) => e.diff ?? 0),
        line: { color: "#dc2626", width: 2 },
        yaxis: "y2",
      });
    }
    // revision event markers
    out.push({
      type: "scatter", mode: "markers", name: "修订事件",
      x: data.events.map((e) => e.ts_utc),
      y: data.events.map((e) => e.new_value ?? e.prev_value ?? 0),
      marker: { color: "#dc2626", size: 9, symbol: "x" },
      customdata: data.events.map((e) => ({ event: e })),
      hovertemplate: "<b>%{x}</b><br>kind: %{customdata.event.revision_kind}<br>" +
                     "prev: %{customdata.event.prev_value}<br>" +
                     "new: %{customdata.event.new_value}<extra></extra>",
    });
    return out;
  }, [data, mode]);

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-2 border-b border-ink-200 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink-900">
          Revision Timeline · <span className="font-mono text-ink-700">{data.field_name}</span>
        </h3>
        <div className="flex gap-1">
          {(["as_known", "latest", "diff"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`text-xs px-2 py-0.5 rounded border ${
                mode === m
                  ? "bg-brand-50 border-brand-500 text-brand-700"
                  : "bg-white border-ink-200 text-ink-500 hover:border-ink-300"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>
      <Plot
        data={traces}
        layout={{
          autosize: true,
          height,
          margin: { l: 50, r: 50, t: 12, b: 36 },
          paper_bgcolor: "white",
          plot_bgcolor: "white",
          hovermode: "closest",
          xaxis: { type: "date", gridcolor: "#f1f5f9", tickfont: { size: 10, color: "#64748b" } },
          yaxis: { title: { text: data.field_name, font: { size: 10 } }, gridcolor: "#f1f5f9", tickfont: { size: 10 } },
          yaxis2: { overlaying: "y", side: "right", title: { text: "delta", font: { size: 10 } }, showgrid: false, tickfont: { size: 10 } },
          legend: { orientation: "h", y: -0.18, font: { size: 10 } },
        } as any}
        config={{ displaylogo: false, responsive: true }}
        style={{ width: "100%", height: `${height}px` }}
        onClick={(ev: any) => {
          if (ev.points?.[0]?.customdata?.event) {
            const e = ev.points[0].customdata.event;
            // open the evidence drawer with the first evidence for that vintage
            openEvidence(`${e.source_id}::${e.field_name ?? data.field_name}::${e.vintage_date}`);
          }
        }}
      />
      <div className="px-4 py-2 text-xs text-ink-500 border-t border-ink-200">
        {data.events.length} 个修订事件 · 最近的: {data.events.at(-1) ? formatTimestamp(data.events.at(-1)!.ts_utc, false) : "—"}
      </div>
    </div>
  );
}
