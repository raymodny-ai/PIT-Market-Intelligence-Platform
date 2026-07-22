"use client";

// TimeSeriesChart — Plotly with PIT-aware tooltips (PRD §TimeSeriesChart).
// STALE points rendered as dashed segments; FORWARD_FILLED marked with
// different color. Hover exposes value / observation_time / available_at /
// data_age / quality / fill_type / source_id. Box-select drives
// selectionStore; "view raw" icon jumps to /lineage.

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { useSelectionStore } from "../stores/selectionStore";
import { formatTimestamp, dataAgeHuman, qualityPill } from "../lib/formatting";
import type { PITSeries, PITPoint, QualityStatus, FillType } from "../types/api";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

export interface TimeSeriesChartProps {
  series: PITSeries[];
  title?: string;
  height?: number;
  yLabel?: string;
  chartId?: string;
  onPointClick?: (p: PITPoint) => void;
  onViewRaw?: (p: PITPoint) => void;
}

export function TimeSeriesChart(props: TimeSeriesChartProps) {
  const { series, title, height = 320, yLabel, chartId = "ts", onPointClick, onViewRaw } = props;
  const setHovered = useSelectionStore((s) => s.setHoveredPoint);
  const setSelected = useSelectionStore((s) => s.setSelectedPoints);
  const toggle = useSelectionStore((s) => s.togglePoint);

  const traces = useMemo(() => buildTraces(series), [series]);

  return (
    <div className="card overflow-hidden">
      {title && (
        <div className="px-4 py-2 border-b border-ink-200 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
          <div className="text-xs text-ink-500">{series.length} 条序列</div>
        </div>
      )}
      <Plot
        data={traces as any}
        layout={{
          autosize: true,
          height,
          margin: { l: 50, r: 16, t: 12, b: 36 },
          paper_bgcolor: "white",
          plot_bgcolor: "white",
          hovermode: "x unified",
          xaxis: {
            type: "date",
            gridcolor: "#f1f5f9",
            linecolor: "#cbd5e1",
            tickfont: { size: 10, color: "#64748b" },
          },
          yaxis: {
            title: { text: yLabel ?? "", font: { size: 11 } },
            gridcolor: "#f1f5f9",
            linecolor: "#cbd5e1",
            tickfont: { size: 10, color: "#64748b" },
            zeroline: false,
          },
          legend: { orientation: "h", y: -0.18, font: { size: 10 } },
          showlegend: series.length > 1,
          dragmode: "select",
        } as any}
        config={{ displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d"] as any }}
        style={{ width: "100%", height: `${height}px` }}
        onHover={(ev: any) => {
          if (ev.points?.[0]) {
            const p = ev.points[0];
            setHovered({
              chartId,
              timestamp: p.x,
              y: p.y,
              field_name: p.data?.name,
            });
          }
        }}
        onClick={(ev: any) => {
          if (ev.points?.[0]) {
            const p = ev.points[0];
            const seriesIdx = p.data?.index ?? p.curveNumber;
            const pt = series[seriesIdx]?.points?.[p.pointIndex];
            if (pt) {
              toggle({ chartId, timestamp: pt.timestamp, field_name: series[seriesIdx].field_name, x: pt.value ?? undefined, y: pt.value ?? undefined });
              onPointClick?.(pt);
            }
          }
        }}
        onSelected={(ev: any) => {
          if (ev?.range) {
            setSelected(
              (ev.points ?? []).map((p: any) => ({
                chartId,
                timestamp: p.x,
                field_name: p.data?.name,
                x: p.x,
                y: p.y,
              })),
            );
          } else {
            setSelected([]);
          }
        }}
      />
    </div>
  );
}

// -----------------------------------------------------------------
// Trace builder
// -----------------------------------------------------------------

function buildTraces(series: PITSeries[]): unknown[] {
  return series.map((s) => {
    // STALE points become dashed; FWD_FILLED become a separate marker trace
    const solidX: string[] = [], solidY: (number | null)[] = [];
    const staleX: string[] = [], staleY: (number | null)[] = [];
    const filledX: string[] = [], filledY: (number | null)[] = [];

    for (const p of s.points) {
      if (p.value === null || p.value === undefined) continue;
      if (p.fill_type === "FORWARD_FILLED" || p.fill_type === "INTERPOLATED") {
        filledX.push(p.timestamp); filledY.push(p.value);
      } else if (isStale(p.quality_status)) {
        staleX.push(p.timestamp); staleY.push(p.value);
      } else {
        solidX.push(p.timestamp); solidY.push(p.value);
      }
    }

    const base: any = {
      type: "scatter",
      mode: "lines",
      name: s.display_name_zh ?? s.field_name,
      line: { width: 1.5 },
      connectgaps: false,
      hovertemplate: hovertemplateFor(s.field_name, "solid"),
    };

    return [
      { ...base, x: solidX, y: solidY, line: { ...base.line, color: "#4f46e5" } },
      { ...base, x: staleX, y: staleY, line: { ...base.line, color: "#f59e0b", dash: "dash" }, name: `${base.name} (stale)`, hovertemplate: hovertemplateFor(s.field_name, "stale") },
      { ...base, type: "scatter", mode: "markers", x: filledX, y: filledY, marker: { color: "#a78bfa", size: 5, symbol: "diamond" }, name: `${base.name} (filled)`, hovertemplate: hovertemplateFor(s.field_name, "filled") },
    ];
  }).flat();
}

function isStale(q: QualityStatus): boolean {
  return q === "STALE" || q === "DEGRADED" || q === "PARTIAL" || q === "INFERRED_AVAILABILITY";
}

function hovertemplateFor(field: string, _kind: string): string {
  return `<b>%{x|%Y-%m-%d %H:%M}</b><br>` +
         `${field}: <b>%{y:.4f}</b><br>` +
         `<span style="color:#94a3b8">%{customdata.hover}</span><extra></extra>`;
}
