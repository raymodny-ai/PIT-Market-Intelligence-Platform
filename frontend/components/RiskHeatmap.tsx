"use client";

// RiskHeatmap — Plotly Heatmap (PRD §RiskHeatmap).
// X = symbols, Y = domains, cell value = z-score (-3..+3),
// diverging blue→white→red. Click cell → setCellSelection in selectionStore.

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { useSelectionStore } from "../stores/selectionStore";
import { useSliceStore } from "../stores/sliceStore";
import { zScoreColor } from "../lib/formatting";
import type { HeatmapResponse, HeatmapCell } from "../types/api";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

export interface RiskHeatmapProps {
  data: HeatmapResponse;
  height?: number;
}

export function RiskHeatmap({ data, height = 360 }: RiskHeatmapProps) {
  const setCellSelection = useSelectionStore((s) => s.setCellSelection);
  const setSymbols = useSliceStore((s) => s.setSymbols);

  const { z, text, customdata } = useMemo(() => buildMatrix(data), [data]);

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-2 border-b border-ink-200 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink-900">风险热图</h3>
        <div className="text-xs text-ink-500">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-pit-zpos align-middle" /> 多头
          <span className="mx-2" />
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-pit-zmid align-middle" /> 中性
          <span className="mx-2" />
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-pit-zneg align-middle" /> 空头
        </div>
      </div>
      <Plot
        data={[{
          type: "heatmap",
          x: data.symbols,
          y: data.domains,
          z,
          text,
          customdata,
          hovertemplate: "<b>%{x}</b> / %{y}<br>" +
                         "z: <b>%{z:.2f}</b><br>" +
                         "quality: %{customdata.q}<br>" +
                         "available_at: %{customdata.avail}<extra></extra>",
          colorscale: [
            [0, "#2563eb"], [0.5, "#f3f4f6"], [1, "#dc2626"],
          ],
          zmin: -3, zmax: 3,
          showscale: true,
          colorbar: { thickness: 8, len: 0.7, tickfont: { size: 9 } },
        }] as any}
        layout={{
          autosize: true,
          height,
          margin: { l: 90, r: 16, t: 8, b: 50 },
          paper_bgcolor: "white",
          plot_bgcolor: "white",
          xaxis: { side: "bottom", tickfont: { size: 11 } },
          yaxis: { autorange: "reversed", tickfont: { size: 10 } },
        } as any}
        config={{ displaylogo: false, responsive: true }}
        style={{ width: "100%", height: `${height}px` }}
        onClick={(ev: any) => {
          if (ev.points?.[0]) {
            const p = ev.points[0];
            const symbol = p.x as string;
            const domain = p.y as string;
            setCellSelection({ symbol, domain });
            // also add this symbol to slice symbols if not already
            const cur = useSliceStore.getState().symbols;
            if (!cur.includes(symbol)) setSymbols([...cur, symbol]);
          }
        }}
      />
    </div>
  );
}

function buildMatrix(data: HeatmapResponse) {
  const idxSym = new Map(data.symbols.map((s, i) => [s, i] as const));
  const idxDom = new Map(data.domains.map((d, i) => [d, i] as const));
  const z: (number | null)[][] = data.domains.map(() =>
    data.symbols.map(() => null as number | null),
  );
  const text: string[][] = data.domains.map(() =>
    data.symbols.map(() => ""),
  );
  const customdata: any[][] = data.domains.map(() =>
    data.symbols.map(() => ({})),
  );

  for (const c of data.cells) {
    const si = idxSym.get(c.canonical_symbol);
    const di = idxDom.get(c.domain);
    if (si === undefined || di === undefined) continue;
    z[di][si] = c.z_score ?? null;
    text[di][si] = c.z_score !== null ? c.z_score.toFixed(2) : "—";
    customdata[di][si] = {
      q: c.quality_status,
      avail: c.available_at ?? "",
      color: zScoreColor(c.z_score),
    };
  }
  return { z, text, customdata };
}
