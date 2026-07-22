"use client";

import * as React from "react";

export interface FindingData {
  finding_id: string;
  title_zh: string;
  claim_zh: string;
  classification: string;
  support_type: string;
  llm_confidence: number;
  final_confidence: number;
  evidence_ids: string[];
  limitations_zh: string[];
}

export interface EvidenceSummary {
  evidence_id: string;
  symbol: string;
  field_name: string;
  value: number;
  state: string;
  age_hours: number;
  semantic_caveat_zh: string;
}

export function FindingCard({ finding }: { finding: FindingData }) {
  const [showEvidence, setShowEvidence] = React.useState(false);

  return (
    <article
      style={{
        border: "1px solid var(--border)",
        borderRadius: "8px",
        padding: "1rem",
        background: "white",
        marginBottom: "1rem",
      }}
    >
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h3 style={{ margin: 0, fontSize: "15px" }}>{finding.title_zh}</h3>
        <div style={{ display: "flex", gap: "0.5rem", fontSize: "11px", color: "var(--muted)" }}>
          <span
            style={{
              padding: "0.1rem 0.4rem",
              borderRadius: "999px",
              background: "var(--accent)",
              color: "white",
            }}
          >
            {finding.classification}
          </span>
          <span>conf {finding.final_confidence.toFixed(2)}</span>
        </div>
      </header>

      <p style={{ margin: "0.5rem 0", fontSize: "13px" }}>{finding.claim_zh}</p>

      <details style={{ marginTop: "0.5rem" }}>
        <summary style={{ fontSize: "12px", color: "var(--muted)", cursor: "pointer" }}>
          Limitations ({finding.limitations_zh.length})
        </summary>
        <ul style={{ fontSize: "12px", margin: "0.5rem 0", paddingLeft: "1.5rem" }}>
          {finding.limitations_zh.map((l, i) => (
            <li key={i} style={{ marginBottom: "0.25rem" }}>{l}</li>
          ))}
        </ul>
      </details>

      <button
        type="button"
        onClick={() => setShowEvidence(!showEvidence)}
        style={{
          marginTop: "0.5rem",
          fontSize: "12px",
          padding: "0.25rem 0.75rem",
          border: "1px solid var(--accent)",
          background: showEvidence ? "var(--accent)" : "white",
          color: showEvidence ? "white" : "var(--accent)",
          borderRadius: "4px",
          cursor: "pointer",
        }}
      >
        {showEvidence ? "Hide" : "View"} {finding.evidence_ids.length} Evidence
      </button>

      {showEvidence && (
        <EvidenceList evidenceIds={finding.evidence_ids} />
      )}
    </article>
  );
}

function EvidenceList({ evidenceIds }: { evidenceIds: string[] }) {
  const [data, setData] = React.useState<EvidenceSummary[] | null>(null);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      // For Phase 3: fetch evidence via /v1/analyses/evidence/{panel_id}
      // and filter by IDs. Simplified: fetch latest panel evidence.
      try {
        const r = await fetch("/v1/panels/latest");
        if (!r.ok) return;
        const panel = await r.json();
        const r2 = await fetch(`/v1/analyses/evidence/${panel.panel_id}`, { method: "POST" });
        if (!r2.ok) return;
        const all = await r2.json();
        if (!cancelled) {
          setData(all.sample.filter((e: EvidenceSummary) => evidenceIds.includes(e.evidence_id)));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [evidenceIds.join(",")]);

  if (loading) return <p style={{ fontSize: "12px", color: "var(--muted)" }}>Loading evidence…</p>;
  if (!data || data.length === 0) return <p style={{ fontSize: "12px", color: "var(--muted)" }}>No evidence available.</p>;

  return (
    <div style={{ marginTop: "0.5rem", borderTop: "1px solid var(--border)", paddingTop: "0.5rem" }}>
      {data.map((e) => (
        <div
          key={e.evidence_id}
          style={{
            border: "1px solid var(--border)",
            borderRadius: "4px",
            padding: "0.5rem",
            marginBottom: "0.5rem",
            fontSize: "12px",
            background: "#fafafa",
          }}
        >
          <div style={{ fontFamily: "ui-monospace, monospace", color: "var(--muted)" }}>
            {e.evidence_id}
          </div>
          <div>
            <strong>{e.symbol}</strong> · {e.field_name} = <code>{e.value}</code> · state={e.state} · age={e.age_hours.toFixed(1)}h
          </div>
          {e.semantic_caveat_zh && (
            <div style={{ color: "var(--degraded)", marginTop: "0.25rem" }}>
              ⚠ {e.semantic_caveat_zh}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
