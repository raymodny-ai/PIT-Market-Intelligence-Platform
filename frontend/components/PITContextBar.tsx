// PIT Context Bar — must always show decision_time, panel_id, panel_version,
// quality, feature version, and data cutoff. PRD §13.1.
import * as React from "react";

export type QualityStatus =
  | "GOOD"
  | "DEGRADED"
  | "STALE"
  | "PARTIAL"
  | "REJECTED"
  | "EPHEMERAL";

export interface PITContextBarProps {
  panelId: string;
  decisionTime: string;
  panelVersion: string;
  qualityStatus: QualityStatus;
  qualityScore?: number;
  featureVersion: string;
  dataCutoff: string;
}

const QUALITY_COLORS: Record<QualityStatus, string> = {
  GOOD: "var(--good)",
  DEGRADED: "var(--degraded)",
  STALE: "var(--stale)",
  PARTIAL: "var(--partial)",
  REJECTED: "var(--rejected)",
  EPHEMERAL: "var(--ephemeral)",
};

export function PITContextBar(props: PITContextBarProps) {
  const score = props.qualityScore?.toFixed(2) ?? "—";
  return (
    <header
      style={{
        display: "flex",
        gap: "1.5rem",
        alignItems: "center",
        padding: "0.75rem 1.5rem",
        background: "#f9fafb",
        borderBottom: "1px solid var(--border)",
        fontSize: "12px",
        fontFamily: "ui-monospace, monospace",
        flexWrap: "wrap",
      }}
    >
      <div>
        <span style={{ color: "var(--muted)" }}>PIT Decision Time:</span>{" "}
        <strong>{props.decisionTime}</strong>
      </div>
      <div>
        <span style={{ color: "var(--muted)" }}>Panel:</span>{" "}
        <strong>{props.panelId}</strong>
      </div>
      <div>
        <span style={{ color: "var(--muted)" }}>Version:</span>{" "}
        <strong>{props.panelVersion}</strong>
      </div>
      <div>
        <span style={{ color: "var(--muted)" }}>Quality:</span>{" "}
        <strong style={{ color: QUALITY_COLORS[props.qualityStatus] }}>
          {props.qualityStatus} ({score})
        </strong>
      </div>
      <div>
        <span style={{ color: "var(--muted)" }}>Features:</span>{" "}
        <strong>{props.featureVersion}</strong>
      </div>
      <div>
        <span style={{ color: "var(--muted)" }}>Data Cutoff:</span>{" "}
        <strong>{props.dataCutoff}</strong>
      </div>
    </header>
  );
}
