"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { PITContextBar } from "@/components/PITContextBar";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { EmptyState } from "@/components/EmptyState";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

interface SourceStatus {
  source_name: string;
  run_count: number;
  total_records: number;
  error_count: number;
  last_run_utc: string | null;
  last_quality_status: string | null;
}

async function fetchStatus(): Promise<{ sources: Record<string, SourceStatus>; as_of_utc: string }> {
  const r = await fetch("/v1/sources/status");
  if (!r.ok) throw new Error(`sources/status: ${r.status}`);
  return r.json();
}

async function fetchEvents(sourceName: string): Promise<{ events: Array<{ ingest_date: string; dataset: string; record_count: number; quality_status: string }> }> {
  const r = await fetch(`/v1/sources/${sourceName}/events`);
  if (!r.ok) throw new Error(`events: ${r.status}`);
  return r.json();
}

const SOURCE_LABELS: Record<string, string> = {
  yfinance: "Yahoo Finance",
  fred: "FRED / ALFRED",
  cftc: "CFTC COT",
  finra: "FINRA Reg SHO",
  finra_otc: "FINRA OTC",
  sec: "SEC EDGAR",
  cboe_cfe: "Cboe CFE",
  etf_issuer: "ETF Issuers",
};

export default function HealthPage() {
  const status = useQuery({ queryKey: ["source-status"], queryFn: fetchStatus, refetchInterval: 30_000 });

  return (
    <ErrorBoundary>
      <PITContextBar
        panelId="—"
        decisionTime={status.data?.as_of_utc ?? "—"}
        panelVersion="—"
        qualityStatus="EPHEMERAL"
        dataCutoff={status.data?.as_of_utc ?? "—"}
        featureVersion="phase4"
      />
      <main style={{ padding: "2rem", maxWidth: 1100, margin: "0 auto" }}>
        <h2>Source Health Matrix (T-27)</h2>
        <p style={{ color: "var(--muted)", fontSize: "12px" }}>
          Per-source SLA / freshness / error counts. Auto-refreshes every 30s.
        </p>

        {status.isLoading && <p>Loading…</p>}
        {status.isError && <EmptyState title="Backend not reachable" />}
        {status.data && (
          <div>
            {/* Source Health Matrix */}
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: "13px",
                marginTop: "1rem",
              }}
            >
              <thead>
                <tr style={{ background: "#f9fafb" }}>
                  <th style={th}>Source</th>
                  <th style={th}>Runs</th>
                  <th style={th}>Records</th>
                  <th style={th}>Errors</th>
                  <th style={th}>Last Run</th>
                  <th style={th}>Last Status</th>
                </tr>
              </thead>
              <tbody>
                {Object.values(status.data.sources).map((s) => (
                  <tr key={s.source_name} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={td}><strong>{SOURCE_LABELS[s.source_name] ?? s.source_name}</strong></td>
                    <td style={td}>{s.run_count}</td>
                    <td style={td}>{s.total_records.toLocaleString()}</td>
                    <td style={{ ...td, color: s.error_count > 0 ? "var(--partial)" : "inherit" }}>
                      {s.error_count}
                    </td>
                    <td style={td}>{s.last_run_utc ?? "—"}</td>
                    <td style={td}>
                      <StatusBadge status={s.last_quality_status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Revision Timeline: per-source records over time */}
            <section style={{ marginTop: "2rem" }}>
              <h3>Revision Timeline</h3>
              <RevisionTimeline sourceNames={Object.keys(status.data.sources)} />
            </section>
          </div>
        )}
      </main>
    </ErrorBoundary>
  );
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span style={{ color: "var(--muted)" }}>—</span>;
  const color =
    status === "VALID" ? "var(--good)" :
    status === "SOURCE_FAILED" ? "var(--partial)" :
    status === "STALE" ? "var(--stale)" :
    "var(--muted)";
  return (
    <span style={{ color, fontWeight: 600, fontSize: "11px" }}>
      {status}
    </span>
  );
}

function RevisionTimeline({ sourceNames }: { sourceNames: string[] }) {
  const [selected, setSelected] = React.useState<string | null>(sourceNames[0] ?? null);
  const events = useQuery({
    queryKey: ["source-events", selected],
    queryFn: () => (selected ? fetchEvents(selected) : Promise.resolve({ events: [] })),
    enabled: !!selected,
  });

  if (sourceNames.length === 0) {
    return <p style={{ color: "var(--muted)" }}>No sources.</p>;
  }
  return (
    <div>
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        {sourceNames.map((s) => (
          <button
            key={s}
            onClick={() => setSelected(s)}
            style={{
              padding: "0.25rem 0.75rem",
              fontSize: "12px",
              border: "1px solid " + (selected === s ? "var(--accent)" : "var(--border)"),
              background: selected === s ? "var(--accent)" : "white",
              color: selected === s ? "white" : "inherit",
              borderRadius: "999px",
              cursor: "pointer",
            }}
          >
            {s}
          </button>
        ))}
      </div>
      {events.data && events.data.events.length > 0 && (
        <Plot
          data={[{
            x: events.data.events.map((e) => e.ingest_date),
            y: events.data.events.map((e) => e.record_count),
            type: "bar",
            marker: {
              color: events.data.events.map((e) =>
                e.quality_status === "VALID" ? "var(--good)" : "var(--partial)"
              ),
            },
            name: selected ?? "",
          } as unknown as Plotly.Data]}
          layout={{
            title: `Record count per run — ${selected}`,
            height: 280,
            xaxis: { title: "ingest_date" },
            yaxis: { title: "records" },
          } as unknown as Plotly.Layout}
          useResizeHandler
          style={{ width: "100%" }}
        />
      )}
      {events.data && events.data.events.length === 0 && (
        <p style={{ color: "var(--muted)", fontSize: "12px" }}>No events for {selected}.</p>
      )}
    </div>
  );
}

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "0.5rem 0.75rem",
  fontSize: "11px",
  textTransform: "uppercase",
  color: "var(--muted)",
};
const td: React.CSSProperties = {
  padding: "0.5rem 0.75rem",
};
