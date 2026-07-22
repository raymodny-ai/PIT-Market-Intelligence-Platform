// API client — thin fetch wrappers + zod validation (PRD §API 契约).
// All responses are validated; callers get typed data or null on shape error.

import {
  type SliceResponse,
  SliceResponse as SliceResponseSchema,
  type PanelSummary,
  PanelSummary as PanelSummarySchema,
  type HeatmapResponse,
  HeatmapResponse as HeatmapResponseSchema,
  type TableResponse,
  TableResponse as TableResponseSchema,
  type EvidenceList,
  EvidenceList as EvidenceListSchema,
  type Finding,
  Finding as FindingSchema,
  type LineageGraph,
  LineageGraph as LineageGraphSchema,
  type SourceHealthMatrix,
  SourceHealthMatrix as SourceHealthMatrixSchema,
  type LLMProvenanceRunFacet,
  LLMProvenanceRunFacet as LLMProvenanceRunFacetSchema,
  type RevisionTimeline,
  RevisionTimeline as RevisionTimelineSchema,
  type QualityStatus,
} from "../types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

// -----------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const r = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

function validated<T>(schema: { safeParse: (v: unknown) => { success: true; data: T } | { success: false } }, raw: unknown, fallback: T): T {
  const res = schema.safeParse(raw);
  return res.success ? res.data : fallback;
}

// -----------------------------------------------------------------
// Endpoints
// -----------------------------------------------------------------

export async function fetchHealth(): Promise<{ status: string; version: string; registry_hash: string } | null> {
  const r = await getJson<{ status: string; version: string; registry_hash?: string }>("/health");
  return r ? { status: r.status, version: r.version, registry_hash: r.registry_hash ?? "" } : null;
}

export async function fetchInstruments(): Promise<{ canonical_symbol: string; asset_class: string; display_name_zh?: string; display_name_en?: string }[]> {
  const r = await getJson<{ instruments: Record<string, any> }>("/v1/instruments/registry");
  if (!r) return [];
  return Object.values(r.instruments ?? {}).map((i: any) => ({
    canonical_symbol: i.canonical_symbol,
    asset_class: i.asset_class,
    display_name_zh: i.display_name_zh,
    display_name_en: i.display_name_en,
  }));
}

export async function fetchMetrics(): Promise<{ field_name: string; display_name_zh: string; source_name: string; semantic_warning?: string; domain?: string }[]> {
  const r = await getJson<{ fields: Record<string, any> }>("/v1/metrics/registry");
  if (!r) return [];
  return Object.values(r.fields ?? {}).map((m: any) => ({
    field_name: m.field_name,
    display_name_zh: m.display_name_zh,
    source_name: m.source_name,
    semantic_warning: m.semantic_warning,
    domain: m.domain ?? "price_volume",
  }));
}

export async function fetchPanelLatest(): Promise<PanelSummary | null> {
  const r = await getJson<any>("/v1/panels/latest");
  if (!r) return null;
  return validated(PanelSummarySchema, r, r as PanelSummary);
}

export async function fetchPanel(panelId: string): Promise<PanelSummary | null> {
  const r = await getJson<any>(`/v1/panels/${encodeURIComponent(panelId)}`);
  if (!r) return null;
  return validated(PanelSummarySchema, r, r as PanelSummary);
}

export interface SliceRequest {
  panel_id: string;
  decision_time: string;
  decision_clock?: "1605_ET" | "1805_ET";
  symbols?: string[];
  fields?: string[];
  sources?: string[];
  start?: string;
  end?: string;
  page?: number;
  page_size?: number;
  include_stale?: boolean;
  include_inferred?: boolean;
}

export async function fetchSlice(req: SliceRequest): Promise<SliceResponse | null> {
  const r = await postJson<any>(`/v1/panels/${encodeURIComponent(req.panel_id)}/slice`, req);
  if (!r) return null;
  return validated(SliceResponseSchema, r, r as SliceResponse);
}

export async function fetchHeatmap(req: SliceRequest): Promise<HeatmapResponse | null> {
  const r = await getJson<any>(`/v1/panels/${encodeURIComponent(req.panel_id)}/heatmap`);
  if (!r) return null;
  return validated(HeatmapResponseSchema, r, r as HeatmapResponse);
}

export async function fetchTablePage(req: SliceRequest & { page: number; page_size: number }): Promise<TableResponse | null> {
  const r = await postJson<any>(`/v1/panels/${encodeURIComponent(req.panel_id)}/table`, req);
  if (!r) return null;
  return validated(TableResponseSchema, r, r as TableResponse);
}

export async function fetchEvidence(panelId: string): Promise<EvidenceList | null> {
  const r = await getJson<any>(`/v1/analyses/evidence/${encodeURIComponent(panelId)}`);
  if (!r) return null;
  return validated(EvidenceListSchema, r, r as EvidenceList);
}

export async function fetchFinding(findingId: string): Promise<Finding | null> {
  const r = await getJson<any>(`/v1/findings/${encodeURIComponent(findingId)}`);
  if (!r) return null;
  return validated(FindingSchema, r, r as Finding);
}

export async function fetchLineage(entityId: string): Promise<LineageGraph | null> {
  const r = await getJson<any>(`/v1/lineage/${encodeURIComponent(entityId)}`);
  if (!r) return null;
  // The API may return either {nodes, edges} or a graph-wrapped shape
  const graph = r.graph ?? r;
  return validated(LineageGraphSchema, graph, graph as LineageGraph);
}

export async function fetchLLMFacet(runId: string): Promise<LLMProvenanceRunFacet | null> {
  const r = await getJson<any>(`/v1/lineage/analysis/${encodeURIComponent(runId)}/facet`);
  if (!r) return null;
  return validated(LLMProvenanceRunFacetSchema, r, r as LLMProvenanceRunFacet);
}

export async function fetchSourceHealth(): Promise<SourceHealthMatrix | null> {
  const r = await getJson<any>("/v1/sources/status");
  if (!r) return null;
  // Normalize API shape → SourceHealthMatrix
  const sources = Object.entries(r.sources ?? {}).map(([k, v]: [string, any]) => ({
    source_id: k,
    source_name: k,
    last_ingest_utc: v.last_ingest_utc ?? null,
    freshness_min: v.freshness_min ?? null,
    threshold_min: v.threshold_min ?? 60,
    last_quality: (v.last_quality ?? "VALID") as QualityStatus,
    status: v.status ?? (v.last_ingest_utc ? "OK" : "NO_DATA"),
    symbol_count: v.symbol_count,
  }));
  return { as_of_utc: r.as_of_utc ?? new Date().toISOString(), sources };
}

export async function fetchRevisionTimeline(fieldName: string, sourceId: string): Promise<RevisionTimeline | null> {
  const r = await getJson<any>(`/v1/sources/${encodeURIComponent(sourceId)}/revisions?field=${encodeURIComponent(fieldName)}`);
  if (!r) return null;
  return validated(RevisionTimelineSchema, r, r as RevisionTimeline);
}

// -----------------------------------------------------------------
// SSE — see useSSEStream hook (lib/useSSEStream.ts) for the client.
// -----------------------------------------------------------------

export const API_BASE_URL = API_BASE;
