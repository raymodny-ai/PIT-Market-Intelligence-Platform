// Centralized TanStack Query keys (PRD §性能要求 — 30~120s staleTime).

export const queryKeys = {
  health: () => ["health"] as const,
  instruments: () => ["instruments"] as const,
  metrics: () => ["metrics"] as const,
  sourceHealth: () => ["source-health"] as const,
  panel: (id: string) => ["panel", id] as const,
  slice: (panelId: string, decisionTime: string) => ["slice", panelId, decisionTime] as const,
  heatmap: (panelId: string) => ["heatmap", panelId] as const,
  table: (panelId: string, page: number) => ["table", panelId, page] as const,
  evidence: (panelId: string) => ["evidence", panelId] as const,
  finding: (id: string) => ["finding", id] as const,
  lineage: (entityId: string) => ["lineage", entityId] as const,
  revision: (field: string, source: string) => ["revision", field, source] as const,
  facet: (runId: string) => ["facet", runId] as const,
};
