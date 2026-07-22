"use client";

import * as React from "react";

export interface LineageNode {
  level: "finding" | "evidence" | "feature" | "observation" | "raw";
  label: string;
  meta: Record<string, string | number>;
}

const LEVEL_LABELS: Record<LineageNode["level"], string> = {
  finding: "Finding",
  evidence: "Evidence Catalog",
  feature: "Feature Observation",
  observation: "Normalized Observation",
  raw: "Raw Record",
};

export function LineageDrawer({ entityId }: { entityId: string }) {
  return (
    <aside
      style={{
        position: "fixed",
        right: 0,
        top: "56px",
        bottom: 0,
        width: "420px",
        background: "white",
        borderLeft: "1px solid var(--border)",
        padding: "1.5rem",
        overflowY: "auto",
        boxShadow: "-2px 0 8px rgba(0,0,0,0.05)",
        zIndex: 100,
      }}
    >
      <h3 style={{ marginTop: 0, fontSize: "14px" }}>Field Lineage</h3>
      <p style={{ fontSize: "11px", color: "var(--muted)" }}>
        entity_id: <code>{entityId}</code>
      </p>
      <ol style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {(Object.keys(LEVEL_LABELS) as LineageNode["level"][]).map((level) => (
          <li
            key={level}
            style={{
              borderLeft: "2px solid var(--accent)",
              paddingLeft: "1rem",
              marginBottom: "1rem",
              position: "relative",
            }}
          >
            <div
              style={{
                position: "absolute",
                left: "-7px",
                top: "0.5rem",
                width: "12px",
                height: "12px",
                borderRadius: "50%",
                background: "var(--accent)",
              }}
            />
            <div style={{ fontSize: "11px", color: "var(--muted)", textTransform: "uppercase" }}>
              {LEVEL_LABELS[level]}
            </div>
            <div style={{ fontFamily: "ui-monospace, monospace", fontSize: "12px" }}>
              {level}::{entityId.slice(0, 24)}
            </div>
          </li>
        ))}
      </ol>
      <p style={{ fontSize: "11px", color: "var(--muted)", marginTop: "1rem" }}>
        OpenLineage 集成在 Phase 4 落地;此处显示静态层级。
      </p>
    </aside>
  );
}
