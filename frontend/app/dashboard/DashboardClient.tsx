"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { useMutation, useQuery } from "@tanstack/react-query";
import { PITContextBar, type QualityStatus } from "@/components/PITContextBar";
import { FilterRail } from "@/components/FilterRail";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { FindingCard, type FindingData } from "@/components/FindingCard";
import { queryKeys } from "@/lib/queryKeys";
import { fetchHealth } from "@/lib/api";
import { useSliceStore } from "@/stores/sliceStore";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

interface PanelSummary {
  panel_id: string;
  panel_sha256: string;
  decision_time: string;
  panel_version: string;
  feature_version: string;
  quality_status: QualityStatus;
  quality_score: number;
  row_count: number;
  field_count: number;
}

interface SlicePoint {
  observation_time: string;
  canonical_symbol: string;
  field_name: string;
  value: number | null;
  source_name?: string | null;
  price_type?: string | null;
}

async function fetchLatestPanel(): Promise<PanelSummary | null> {
  const res = await fetch("/v1/panels/latest");
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`panels/latest: ${res.status}`);
  return res.json();
}

async function fetchSlice(
  panelId: string,
  body: { universe: string[]; fields?: string[]; sources?: string[]; sort?: object; page?: object }
): Promise<{ rows: SlicePoint[]; row_count: number; cache_key: string }> {
  const r = await fetch(`/v1/panels/${panelId}/slice`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`slice: ${r.status}`);
  return r.json();
}

function DashboardClient() {
  const slice = useSliceStore();
  const health = useQuery({ queryKey: queryKeys.health, queryFn: fetchHealth });
  const panel = useQuery({
    queryKey: ["panel-latest"],
    queryFn: fetchLatestPanel,
    retry: false,
  });

  const priceSlice = useQuery({
    queryKey: ["price-slice", slice.selectedSymbols, slice.selectedFields],
    queryFn: () => {
      if (!panel.data) return Promise.resolve({ rows: [] as SlicePoint[], row_count: 0, cache_key: "" });
      return fetchSlice(panel.data.panel_id, {
        universe: slice.selectedSymbols,
        fields: ["price__yf__close"],
        sources: ["yfinance"],
        sort: { field: "observation_time", direction: "asc" },
      });
    },
    enabled: !!panel.data,
    retry: false,
  });

  const crossSection = useQuery({
    queryKey: ["cross-section", slice.selectedSymbols],
    queryFn: () => {
      if (!panel.data) return Promise.resolve({ rows: [] as SlicePoint[], row_count: 0, cache_key: "" });
      return fetchSlice(panel.data.panel_id, {
        universe: slice.selectedSymbols,
        page: { offset: 0, limit: 500 },
      });
    },
    enabled: !!panel.data,
    retry: false,
  });

  const onBrushEnd = React.useCallback(
    (evt: unknown) => {
      const ev = evt as { range?: { x?: [string, string] } };
      if (!ev?.range?.x) return;
      const [start, end] = ev.range.x;
      slice.setDateRange({ start: start.slice(0, 10), end: end.slice(0, 10) });
    },
    [slice]
  );

  const onHeatmapClick = React.useCallback(
    (evt: unknown) => {
      const ev = evt as { points?: Array<{ x?: string }> };
      const p = ev?.points?.[0];
      if (p?.x) slice.setSymbols([p.x]);
    },
    [slice]
  );

  const spySeries = (priceSlice.data?.rows ?? [])
    .filter((r) => r.canonical_symbol === "SPY" && r.value != null)
    .sort((a, b) => a.observation_time.localeCompare(b.observation_time));

  const heatmapRows = React.useMemo(() => {
    const map = new Map<string, Map<string, number | null>>();
    for (const r of crossSection.data?.rows ?? []) {
      if (r.value == null) continue;
      const sym = r.canonical_symbol;
      const src = r.source_name ?? "—";
      if (!map.has(sym)) map.set(sym, new Map());
      map.get(sym)!.set(src, r.value);
    }
    const sources = Array.from(new Set([...map.values()].flatMap((m) => [...m.keys()])));
    const symbols = [...map.keys()];
    const z = symbols.map((s) => sources.map((src) => map.get(s)!.get(src) ?? null));
    return { x: sources, y: symbols, z };
  }, [crossSection.data]);

  // T-23: LLM analysis mutation (Mock provider)
  const analysis = useMutation({
    mutationFn: async (panelId: string) => {
      const r = await fetch("/v1/analyses", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ panel_id: panelId, provider: "mock" }),
      });
      if (!r.ok) throw new Error(`analysis: ${r.status}`);
      return r.json() as Promise<{
        analysis_run_id: string;
        status: string;
        finding: FindingData | null;
        errors: string[];
      }>;
    },
  });

  return (
    <ErrorBoundary>
      <PITContextBar
        panelId={panel.data?.panel_id ?? "no-panel"}
        decisionTime={panel.data?.decision_time ?? "—"}
        panelVersion={panel.data?.panel_version ?? "—"}
        qualityStatus={panel.data?.quality_status ?? "EPHEMERAL"}
        qualityScore={panel.data?.quality_score}
        featureVersion={panel.data?.feature_version ?? "—"}
        dataCutoff={panel.data?.decision_time ?? "—"}
      />
      <div style={{ display: "flex" }}>
        <FilterRail />
        <main style={{ flex: 1, padding: "2rem", minWidth: 0 }}>
          {panel.isLoading && <p>Loading latest panel…</p>}
          {panel.isError && (
            <EmptyState
              title="Backend not reachable"
              description="Start the FastAPI server (port 8000) to see live data."
            />
          )}
          {panel.data === null && (
            <EmptyState
              title="No panel built yet"
              description="Run `pit-market pit build --decision-time ...` to create the first PIT panel."
            />
          )}
          {panel.data && (
            <div style={{ display: "grid", gap: "1.5rem" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1rem" }}>
                <KpiCard label="Rows" value={String(panel.data.row_count)} />
                <KpiCard label="Fields" value={String(panel.data.field_count)} />
                <KpiCard label="Quality" value={panel.data.quality_status} />
                <KpiCard label="Backend" value={health.data?.version ?? "—"} />
              </div>

              {spySeries.length > 0 && (
                <Plot
                  data={[
                    {
                      x: spySeries.map((r) => r.observation_time),
                      y: spySeries.map((r) => r.value),
                      type: "scatter",
                      mode: "lines+markers",
                      name: "SPY close",
                    } as unknown as Plotly.Data,
                  ]}
                  layout={{
                    title: "SPY Daily Close (brush to filter date range)",
                    height: 360,
                    xaxis: { title: "observation_time" },
                    yaxis: { title: "USD" },
                  } as unknown as Plotly.Layout}
                  useResizeHandler
                  style={{ width: "100%" }}
                  onRelayout={(e: unknown) => {
                    const ev = e as { range?: { x?: [string, string] } };
                    if (ev?.range?.x) onBrushEnd({ range: { x: ev.range.x } });
                  }}
                />
              )}

              {heatmapRows.x.length > 0 && (
                <Plot
                  data={[
                    {
                      x: heatmapRows.x,
                      y: heatmapRows.y,
                      z: heatmapRows.z,
                      type: "heatmap",
                      colorscale: "Viridis",
                    } as unknown as Plotly.Data,
                  ]}
                  layout={{
                    title: "Cross-source / Cross-symbol (click to filter)",
                    height: 280,
                  } as unknown as Plotly.Layout}
                  useResizeHandler
                  style={{ width: "100%" }}
                  onClick={onHeatmapClick}
                />
              )}

              <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                Filters synced to URL · date range {slice.dateRange.start} → {slice.dateRange.end}
              </div>

              <section
                style={{
                  marginTop: "1.5rem",
                  borderTop: "1px solid var(--border)",
                  paddingTop: "1.5rem",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <h3 style={{ margin: 0, fontSize: "14px" }}>LLM Findings</h3>
                  <button
                    type="button"
                    onClick={() => panel.data && analysis.mutate(panel.data.panel_id)}
                    disabled={analysis.isPending}
                    style={{
                      padding: "0.4rem 0.75rem",
                      background: "var(--accent)",
                      color: "white",
                      border: 0,
                      borderRadius: "4px",
                      cursor: analysis.isPending ? "wait" : "pointer",
                      opacity: analysis.isPending ? 0.6 : 1,
                    }}
                  >
                    {analysis.isPending ? "Analyzing…" : "Generate Analysis"}
                  </button>
                </div>

                {analysis.isError && (
                  <p style={{ color: "var(--rejected)", fontSize: "12px" }}>
                    Analysis failed: {(analysis.error as Error).message}
                  </p>
                )}
                {analysis.data?.status === "REJECTED" && (
                  <p style={{ color: "var(--degraded)", fontSize: "12px" }}>
                    Finding rejected at validation: {analysis.data.errors.join("; ")}
                  </p>
                )}
                {analysis.data?.finding && (
                  <FindingCard finding={analysis.data.finding} />
                )}
                {!analysis.data && !analysis.isPending && (
                  <p style={{ color: "var(--muted)", fontSize: "12px" }}>
                    Click &ldquo;Generate Analysis&rdquo; to run LLM (mock) on the current panel.
                  </p>
                )}
              </section>
            </div>
          )}
        </main>
      </div>
    </ErrorBoundary>
  );
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: "6px",
        padding: "1rem",
        background: "white",
      }}
    >
      <div style={{ color: "var(--muted)", fontSize: "12px" }}>{label}</div>
      <div style={{ fontSize: "20px", fontWeight: 600, marginTop: "0.25rem" }}>{value}</div>
    </div>
  );
}

export default DashboardClient;
