// API client + zod validation. Phase 0: just /health check.
import { z } from "zod";

const HealthResponseSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  version: z.string(),
  panel_count: z.number().optional(),
});

export type HealthResponse = z.infer<typeof HealthResponseSchema>;

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`health check failed: ${res.status} ${res.statusText}`);
  }
  const json = await res.json();
  return HealthResponseSchema.parse(json);
}
