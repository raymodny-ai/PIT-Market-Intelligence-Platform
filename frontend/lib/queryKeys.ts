// TanStack Query key conventions (Phase 2 uses these heavily).
export const queryKeys = {
  health: ["health"] as const,
  panel: (panelId: string) => ["panel", panelId] as const,
  slice: (panelId: string, requestHash: string) =>
    ["slice", panelId, requestHash] as const,
  evidence: (evidenceId: string) => ["evidence", evidenceId] as const,
  finding: (findingId: string) => ["finding", findingId] as const,
  lineage: (entityId: string) => ["lineage", entityId] as const,
  metricsRegistry: ["metrics-registry"] as const,
  instrumentsRegistry: ["instruments-registry"] as const,
};
