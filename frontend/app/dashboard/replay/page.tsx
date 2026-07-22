"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { PITContextBar, type QualityStatus } from "@/components/PITContextBar";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBoundary } from "@/components/ErrorBoundary";
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

async function fetchPanelAt(panelId: string): Promise<PanelSummary | null> {
  const r = await fetch(`/v1/panels/${panelId}`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`panels/${panelId}: ${r.status}`);
  return r.json();
}

async function fetchLatestPanel(): Promise<PanelSummary | null> {
  const r = await fetch("/v1/panels/latest");
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`panels/latest: ${r.status}`);
  return r.json();
}

export default function ReplayPage() {
  const slice = useSliceStore();
  const [targetDate, setTargetDate] = React.useState<string>(slice.dateRange.end);

  const latest = useQuery({ queryKey: ["panel-latest"], queryFn: fetchLatestPanel });
  const historical = useQuery({
    queryKey: ["panel-replay", targetDate],
    queryFn: async () => {
      if (!latest.data) return null;
      // For Phase 2: pretend panel_id embeds the date. Real impl needs PIT replay.
      return fetchPanelAt(latest.data.panel_id);
    },
    enabled: !!latest.data,
  });

  const onSlide = (e: React.ChangeEvent<HTMLInputElement>) => {
    setTargetDate(e.target.value);
  };

  return (
    <ErrorBoundary>
      <PITContextBar
        panelId={historical.data?.panel_id ?? "—"}
        decisionTime={historical.data?.decision_time ?? "—"}
        panelVersion={historical.data?.panel_version ?? "—"}
        qualityStatus={historical.data?.quality_status ?? "EPHEMERAL"}
        qualityScore={historical.data?.quality_score}
        featureVersion={historical.data?.feature_version ?? "—"}
        dataCutoff={historical.data?.decision_time ?? "—"}
      />
      <main style={{ padding: "2rem" }}>
        <h2>PIT Replay</h2>
        <p style={{ color: "var(--muted)" }}>
          Time-replay mode (PRD §11.4). Pick a date to view a historical panel.
        </p>
        <div style={{ marginTop: "1.5rem" }}>
          <label style={{ display: "block" }}>
            Decision date:
            <input
              type="date"
              value={targetDate}
              onChange={onSlide}
              style={{ padding: "0.4rem", marginLeft: "0.5rem" }}
            />
          </label>
        </div>
        {latest.isLoading && <p>Loading…</p>}
        {latest.data === null && (
          <EmptyState title="No panel built yet" description="Build the first PIT panel to use replay." />
        )}
        {historical.data && (
          <div style={{ marginTop: "1.5rem" }}>
            <Plot
              data={[
                {
                  x: [historical.data.decision_time],
                  y: [historical.data.quality_score],
                  type: "scatter",
                  mode: "markers",
                  marker: { size: 20 },
                  name: "Quality score",
                } as unknown as Plotly.Data,
              ]}
              layout={{ title: "Replay snapshot", height: 280 } as unknown as Plotly.Layout}
              useResizeHandler
              style={{ width: "100%" }}
            />
            <p style={{ fontSize: "12px", color: "var(--muted)" }}>
              Panel at <code>{historical.data.decision_time}</code> ·{" "}
              quality <code>{historical.data.quality_status}</code>
            </p>
          </div>
        )}
      </main>
    </ErrorBoundary>
  );
}
