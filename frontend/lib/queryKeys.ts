// Centralized TanStack Query keys (PRD §性能要求 — 30~120s staleTime).

export const queryKeys = {
  health: () => ["health"] as const,
  instruments: () => ["instruments"] as const,
  metrics: () => ["metrics"] as const,
  sourceHealth: () => ["source-health"] as const,
  panel: (id: string) => ["panel", id] as const,
  panels: () => ["panels"] as const,
  slice: (panelId: string, decisionTime: string) => ["slice", panelId, decisionTime] as const,
  heatmap: (panelId: string) => ["heatmap", panelId] as const,
  table: (panelId: string, page: number) => ["table", panelId, page] as const,
  evidence: (panelId: string) => ["evidence", panelId] as const,
  finding: (id: string) => ["finding", id] as const,
  lineage: (entityId: string) => ["lineage", entityId] as const,
  revision: (field: string, source: string) => ["revision", field, source] as const,
  facet: (runId: string) => ["facet", runId] as const,
  // T-47 extended keys
  snapshots: (panelId: string) => ["snapshots", panelId] as const,
  snapshot: (panelId: string, date: string) => ["snapshot", panelId, date] as const,
  reports: () => ["reports"] as const,
  task: (jobId: string) => ["task", jobId] as const,
  tasks: () => ["tasks"] as const,
  backtestResult: (jobId: string) => ["backtest-result", jobId] as const,
  systemHealth: () => ["system-health"] as const,
  registry: () => ["registry"] as const,
};
