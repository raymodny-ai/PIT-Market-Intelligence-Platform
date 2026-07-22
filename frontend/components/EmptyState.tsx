import * as React from "react";

export interface EmptyStateProps {
  title: string;
  description?: string;
  children?: React.ReactNode;
}

export function EmptyState({ title, description, children }: EmptyStateProps) {
  return (
    <div
      style={{
        padding: "2rem",
        textAlign: "center",
        color: "var(--muted)",
        border: "1px dashed var(--border)",
        borderRadius: "6px",
      }}
    >
      <h3 style={{ margin: "0 0 0.5rem 0", color: "var(--fg)" }}>{title}</h3>
      {description && <p style={{ margin: 0 }}>{description}</p>}
      {children}
    </div>
  );
}
