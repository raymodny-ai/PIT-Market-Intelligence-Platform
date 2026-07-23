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
  type PanelListResponse,
  PanelListResponse as PanelListResponseSchema,
  type PanelListEntry,
  type LLMProvenanceRunFacet,
  LLMProvenanceRunFacet as LLMProvenanceRunFacetSchema,
  type RevisionTimeline,
  RevisionTimeline as RevisionTimelineSchema,
  type QualityStatus,
  type AsyncTask,
  type SystemHealth,
  type BacktestResult,
  type SnapshotDate,
  type RegistryEntry,
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

// Tri-state result for endpoints where callers need to surface server-side
// validation errors (4xx with a JSON detail body) rather than treat them
// as "no response". Most call sites still want postJson()'s T|null.
export type JsonResult<T> =
  | { ok: true; data: T; status: number }
  | { ok: false; status: number; detail: string };

/** POST that exposes the server's error body. Used by buildPanel() so the
 *  UI can show Pydantic validation messages, not a generic "no response". */
async function postJsonWithError<T>(path: string, body: unknown): Promise<JsonResult<T>> {
  let r: Response;
  try {
    r = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (e) {
    return { ok: false, status: 0, detail: `网络错误: ${(e as Error).message}` };
  }
  // Always try to parse JSON, even on 4xx — FastAPI puts detail in the body.
  const text = await r.text();
  let parsed: any = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      // non-JSON body; fall through with raw text
    }
  }
  if (r.ok) {
    return { ok: true, data: parsed as T, status: r.status };
  }
  // 4xx / 5xx: surface the FastAPI detail (string OR Pydantic error array).
  const detail = formatErrorDetail(parsed, text, r.status);
  return { ok: false, status: r.status, detail };
}

function formatErrorDetail(parsed: any, rawText: string, status: number): string {
  if (!parsed) return `HTTP ${status}: ${rawText.slice(0, 200) || "(empty body)"}`;
  if (typeof parsed.detail === "string") return parsed.detail;
  if (Array.isArray(parsed.detail)) {
    // Pydantic validation error array — pull out field+msg.
    return parsed.detail
      .map((e: any) => {
        const loc = Array.isArray(e.loc) ? e.loc.join(".") : "?";
        return `${loc}: ${e.msg ?? "invalid"}`;
      })
      .join("; ");
  }
  return `HTTP ${status}: ${JSON.stringify(parsed).slice(0, 200)}`;
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
  // The API responses with instruments keyed by canonical_symbol, but the field
  // itself is omitted from the inner objects — fall back to the key so callers
  // always have a non-empty canonical_symbol to render.
  return Object.entries(r.instruments ?? {}).map(([key, i]: [string, any]) => ({
    canonical_symbol: i.canonical_symbol ?? key,
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

export async function fetchPanelsList(): Promise<PanelListResponse | null> {
  const r = await getJson<any>("/v1/panels");
  if (!r) return null;
  return validated(PanelListResponseSchema, r, { panels: [], count: 0 });
}

export interface BuildPanelRequest {
  decision_time: string;        // ISO-8601
  universe: string[];           // canonical_symbols
  decision_clock?: "1605_ET" | "1805_ET";
}

export interface BuildPanelResponse {
  panel_id: string;
  decision_time_utc: string;
  decision_clock: string;
  universe: string[];
  registry_hash: string;
  feature_version: string;
  metric_registry_version: string;
  instrument_registry_version: string;
}

/** Result of a build-panel attempt. Either ok with the manifest, or
 *  not-ok with a server-provided error string. Callers should check
 *  the discriminated union instead of relying on null. */
export type BuildPanelResult =
  | { ok: true; status: number; data: BuildPanelResponse }
  | { ok: false; status: number; detail: string };

export async function buildPanel(req: BuildPanelRequest): Promise<BuildPanelResult> {
  return postJsonWithError<BuildPanelResponse>("/v1/panels/build", {
    decision_clock: "1805_ET",
    ...req,
  });
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
// T-46 extended API endpoints
// -----------------------------------------------------------------

export async function fetchPanels(): Promise<PanelSummary[]> {
  const r = await getJson<any>("/v1/panels");
  if (!r) return [];
  const items = r.panels ?? r.items ?? r;
  return Array.isArray(items) ? items : [];
}

export async function triggerPanelBuild(body: { symbols?: string[]; decision_time?: string; force_rebuild?: boolean }): Promise<AsyncTask | null> {
  return postJson<AsyncTask>("/api/v1/panels/build", body);
}

export async function fetchSnapshots(panelId: string): Promise<SnapshotDate[]> {
  const r = await getJson<any>(`/api/v1/panels/${encodeURIComponent(panelId)}/snapshots`);
  if (!r) return [];
  return Array.isArray(r) ? r : (r.snapshots ?? []);
}

export async function triggerReportBuild(body: { panel_id?: string; symbols?: string[]; language?: string }): Promise<AsyncTask | null> {
  return postJson<AsyncTask>("/api/v1/report/build", body);
}

export async function fetchReports(): Promise<any[]> {
  const r = await getJson<any>("/api/v1/reports");
  if (!r) return [];
  return Array.isArray(r) ? r : (r.reports ?? []);
}

export async function triggerBacktest(body: { strategy: string; symbols?: string[]; start_date?: string; end_date?: string; params?: Record<string, any> }): Promise<AsyncTask | null> {
  return postJson<AsyncTask>("/api/v1/backtest/run", body);
}

export async function fetchBacktestResult(jobId: string): Promise<BacktestResult | null> {
  return getJson<BacktestResult>(`/api/v1/backtest/${encodeURIComponent(jobId)}/results`);
}

export async function fetchTask(jobId: string): Promise<AsyncTask | null> {
  return getJson<AsyncTask>(`/api/v1/system/tasks/${encodeURIComponent(jobId)}`);
}

export async function cancelTask(jobId: string): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/system/tasks/${encodeURIComponent(jobId)}/cancel`, { method: "POST", cache: "no-store" });
    return r.ok;
  } catch {
    return false;
  }
}

export async function fetchSystemHealth(): Promise<SystemHealth | null> {
  return getJson<SystemHealth>("/api/v1/system/health");
}

export async function fetchSystemTasks(): Promise<AsyncTask[]> {
  const r = await getJson<any>("/api/v1/system/tasks");
  if (!r) return [];
  return Array.isArray(r) ? r : (r.tasks ?? []);
}

export async function triggerSync(body: { symbols?: string[]; full_refresh?: boolean }): Promise<AsyncTask | null> {
  return postJson<AsyncTask>("/api/v1/sync", body);
}

export async function fetchRegistry(): Promise<{ instruments: RegistryEntry[]; metrics: RegistryEntry[] }> {
  const [instruments, metrics] = await Promise.all([
    fetchInstruments(),
    fetchMetrics(),
  ]);
  return {
    instruments: instruments.map((i) => ({
      name: i.canonical_symbol,
      asset_class: i.asset_class,
      display_name_zh: i.display_name_zh,
      type: "instrument",
    })),
    metrics: metrics.map((m) => ({
      name: m.field_name,
      display_name_zh: m.display_name_zh,
      source: m.source_name,
      type: "metric",
    })),
  };
}

export function exportCsvUrl(panelId: string): string {
  return `${API_BASE}/api/v1/export/csv?panel_id=${encodeURIComponent(panelId)}`;
}

export function exportParquetUrl(panelId: string): string {
  return `${API_BASE}/api/v1/export/parquet?panel_id=${encodeURIComponent(panelId)}`;
}

export const SSE_BUILD_URL = (jobId: string) =>
  `${API_BASE}/api/v1/panels/build/stream?job_id=${encodeURIComponent(jobId)}`;

// -----------------------------------------------------------------
// SSE — see useSSEStream hook (lib/useSSEStream.ts) for the client.
// -----------------------------------------------------------------

export const API_BASE_URL = API_BASE;
