// API types — Zod schemas + derived TS types (PRD §前端技术规范).
// All API responses are validated at runtime with these schemas; the
// resulting TS types are the source of truth for the UI layer.

import { z } from "zod";

// -----------------------------------------------------------------
// Enums (PRD §质量状态 / §LLM状态机)
// -----------------------------------------------------------------

export const QualityStatus = z.enum([
  "VALID",
  "DEGRADED",
  "STALE",
  "PARTIAL",
  "REJECTED",
  "INFERRED_AVAILABILITY",
  "SOURCE_FAILED",
  "SOURCE_THROTTLED",
  "EMPTY_RESPONSE",
]);
export type QualityStatus = z.infer<typeof QualityStatus>;

export const FieldState = z.enum([
  "LOW_EXTREME",
  "LOW",
  "NEUTRAL",
  "HIGH",
  "HIGH_EXTREME",
  "MISSING",
  "STALE",
  "INFERRED_AVAILABILITY",
]);
export type FieldState = z.infer<typeof FieldState>;

export const FillType = z.enum([
  "OBSERVED",
  "FORWARD_FILLED",
  "INTERPOLATED",
  "DERIVED",
]);
export type FillType = z.infer<typeof FillType>;

export const AnalysisStage = z.enum([
  "QUEUED",
  "EVIDENCE_READY",
  "LLM_RUNNING",
  "VALIDATING",
  "PUBLISHED",
  "REJECTED",
]);
export type AnalysisStage = z.infer<typeof AnalysisStage>;

// -----------------------------------------------------------------
// PIT Point / Series / Panel
// -----------------------------------------------------------------

export const PITPoint = z.object({
  timestamp: z.string(),                 // ISO 8601 — observation_time
  value: z.number().nullable(),
  available_at: z.string(),              // PIT anchor
  observation_time: z.string().optional(),
  quality_status: QualityStatus.default("VALID"),
  fill_type: FillType.default("OBSERVED"),
  source_id: z.string().optional(),
  semantic_warning: z.string().optional(),
  data_age_hours: z.number().nonnegative().optional(),
});
export type PITPoint = z.infer<typeof PITPoint>;

export const PITSeries = z.object({
  field_name: z.string(),
  display_name_zh: z.string().optional(),
  unit: z.string().optional(),
  semantic_warning: z.string().optional(),
  points: z.array(PITPoint),
});
export type PITSeries = z.infer<typeof PITSeries>;

export const SliceResponse = z.object({
  panel_id: z.string(),
  decision_time: z.string(),
  fields: z.array(z.string()),
  series: z.array(PITSeries),
  // Backward-compat with old shape:
  points: z.array(z.any()).optional(),
});
export type SliceResponse = z.infer<typeof SliceResponse>;

// -----------------------------------------------------------------
// Panel summary
// -----------------------------------------------------------------

export const PanelSummary = z.object({
  panel_id: z.string(),
  panel_sha256: z.string().optional(),
  decision_time: z.string(),
  panel_version: z.string(),
  feature_version: z.string().optional(),
  quality_status: QualityStatus,
  quality_score: z.number().optional(),
  row_count: z.number().int().nonnegative().optional(),
  field_count: z.number().int().nonnegative().optional(),
  instrument_registry_version: z.string().optional(),
  metric_registry_version: z.string().optional(),
  registry_hash: z.string().optional(),
  // List endpoint may attach filesystem metadata (relative to panels_dir).
  _path: z.string().optional(),
  _mtime_utc: z.string().optional(),
  _size_bytes: z.number().int().nonnegative().optional(),
});
export type PanelSummary = z.infer<typeof PanelSummary>;

export const PanelList = z.object({
  panels: z.array(PanelSummary),
  count: z.number().int().nonnegative(),
});
export type PanelList = z.infer<typeof PanelList>;

// PanelListEntry — what /v1/panels actually returns per item.
// Manifest-shaped (raw on-disk fields) + filesystem metadata, not the
// resolved PanelSummary shape. Use PanelSummary only for /latest and
// /v1/panels/{id} responses.
export const PanelListEntry = z.object({
  panel_id: z.string(),
  decision_time_utc: z.string().optional(),
  decision_clock: z.string().optional(),
  universe: z.array(z.string()).optional(),
  registry_hash: z.string().optional(),
  feature_version: z.string().optional(),
  metric_registry_version: z.string().optional(),
  instrument_registry_version: z.string().optional(),
  // Filesystem metadata attached by /v1/panels.
  _path: z.string().optional(),
  _mtime_utc: z.string().optional(),
  _size_bytes: z.number().int().nonnegative().optional(),
});
export type PanelListEntry = z.infer<typeof PanelListEntry>;

export const PanelListResponse = z.object({
  panels: z.array(PanelListEntry),
  count: z.number().int().nonnegative(),
});
export type PanelListResponse = z.infer<typeof PanelListResponse>;

// -----------------------------------------------------------------
// AG Grid table (PIT panel wide-table)
// -----------------------------------------------------------------

export const TableRow = z.object({
  canonical_symbol: z.string(),
  decision_time: z.string(),
  panel_version: z.string(),
  // price block
  close_raw: z.number().nullable().optional(),
  close_adj: z.number().nullable().optional(),
  z_score_63d: z.number().nullable().optional(),
  return_1d: z.number().nullable().optional(),
  return_5d: z.number().nullable().optional(),
  // macro
  real_rate_10y: z.number().nullable().optional(),
  dxy_z_score: z.number().nullable().optional(),
  vix_level: z.number().nullable().optional(),
  hy_spread: z.number().nullable().optional(),
  // COT
  managed_money_net: z.number().nullable().optional(),
  cot_net_pct_oi: z.number().nullable().optional(),
  crowd_score: z.number().nullable().optional(),
  // short
  short_ratio_finra: z.number().nullable().optional(),
  short_flow_z_score: z.number().nullable().optional(),
  // meta
  quality_status: QualityStatus,
  fill_type: FillType.optional(),
  evidence_ids: z.array(z.string()).optional(),
});
export type TableRow = z.infer<typeof TableRow>;

export const TablePageInfo = z.object({
  page: z.number().int().min(1),
  page_size: z.number().int().min(1),
  total: z.number().int().nonnegative(),
  has_next: z.boolean(),
});
export type TablePageInfo = z.infer<typeof TablePageInfo>;

export const TableResponse = z.object({
  panel_id: z.string(),
  rows: z.array(TableRow),
  page_info: TablePageInfo,
});
export type TableResponse = z.infer<typeof TableResponse>;

// -----------------------------------------------------------------
// Risk Heatmap
// -----------------------------------------------------------------

export const HeatmapCell = z.object({
  canonical_symbol: z.string(),
  domain: z.string(),
  z_score: z.number().nullable(),
  percentile_rank: z.number().nullable().optional(),
  quality_status: QualityStatus,
  available_at: z.string().optional(),
  semantic_warning: z.string().optional(),
});
export type HeatmapCell = z.infer<typeof HeatmapCell>;

export const HeatmapResponse = z.object({
  panel_id: z.string(),
  symbols: z.array(z.string()),
  domains: z.array(z.string()),
  cells: z.array(HeatmapCell),
});
export type HeatmapResponse = z.infer<typeof HeatmapResponse>;

// -----------------------------------------------------------------
// Evidence
// -----------------------------------------------------------------

export const Evidence = z.object({
  evidence_id: z.string(),
  symbol: z.string().optional(),
  field_name: z.string(),
  display_name_zh: z.string().optional(),
  value: z.number().nullable(),
  unit: z.string().optional(),
  state: FieldState.optional(),
  z_score: z.number().nullable().optional(),
  percentile_rank: z.number().nullable().optional(),
  observation_time: z.string(),
  available_at: z.string(),
  age_hours: z.number().nonnegative().optional(),
  data_age_days: z.number().nonnegative().optional(),
  source_name: z.string(),
  dataset_name: z.string().optional(),
  feature_observation_id: z.string().optional(),
  feature_version: z.string().optional(),
  normalized_observation_id: z.string().optional(),
  fill_type: FillType.optional(),
  raw_record_hash: z.string().optional(),
  feature_definition_id: z.string().optional(),
  quality_status: QualityStatus,
  semantic_caveat_zh: z.string().optional(),
});
export type Evidence = z.infer<typeof Evidence>;

export const EvidenceList = z.object({
  panel_id: z.string(),
  evidence: z.array(Evidence),
});
export type EvidenceList = z.infer<typeof EvidenceList>;

// -----------------------------------------------------------------
// Finding
// -----------------------------------------------------------------

export const Finding = z.object({
  finding_id: z.string(),
  analysis_run_id: z.string().optional(),
  title_zh: z.string().optional(),
  title: z.string().optional(),
  claim_zh: z.string().optional(),
  claim: z.string().optional(),
  classification: z.string().optional(),
  support_type: z.string().optional(),
  causal_language_level: z
    .enum(["ASSOCIATIVE_ONLY", "DESCRIPTIVE", "CAUSAL"])
    .optional(),
  llm_confidence: z.number().min(0).max(1).optional(),
  final_confidence: z.number().min(0).max(1).optional(),
  evidence_ids: z.array(z.string()),
  limitations_zh: z.array(z.string()).optional(),
  limitations: z.array(z.string()).optional(),
  model: z.string().optional(),
  prompt_version: z.string().optional(),
  created_at: z.string().optional(),
  rejected: z.boolean().optional(),
  reject_reason: z.string().optional(),
});
export type Finding = z.infer<typeof Finding>;

// -----------------------------------------------------------------
// Lineage (5-level graph)
// -----------------------------------------------------------------

export const LineageNodeKind = z.enum([
  "finding",
  "evidence",
  "feature",
  "observation",
  "raw",
]);
export type LineageNodeKind = z.infer<typeof LineageNodeKind>;

export const LineageNode = z.object({
  id: z.string(),
  kind: LineageNodeKind,
  label: z.string().optional(),
  sha256: z.string().optional(),
  url: z.string().optional(),
  ts: z.string().optional(),
  meta: z.record(z.any()).optional(),
});
export type LineageNode = z.infer<typeof LineageNode>;

export const LineageEdge = z.object({
  from: z.string(),
  to: z.string(),
  relation: z.string().optional(),
});
export type LineageEdge = z.infer<typeof LineageEdge>;

export const LineageGraph = z.object({
  panel_id: z.string().optional(),
  finding_id: z.string().optional(),
  nodes: z.array(LineageNode),
  edges: z.array(LineageEdge),
});
export type LineageGraph = z.infer<typeof LineageGraph>;

// -----------------------------------------------------------------
// Source Health
// -----------------------------------------------------------------

export const SourceHealthEntry = z.object({
  source_id: z.string(),
  source_name: z.string().optional(),
  last_ingest_utc: z.string().nullable(),
  freshness_min: z.number().nullable(),
  threshold_min: z.number(),
  last_quality: QualityStatus,
  status: z.enum(["OK", "STALE", "FAILED", "THROTTLED", "NO_DATA"]),
  symbol_count: z.number().int().nonnegative().optional(),
});
export type SourceHealthEntry = z.infer<typeof SourceHealthEntry>;

export const SourceHealthMatrix = z.object({
  as_of_utc: z.string(),
  sources: z.array(SourceHealthEntry),
});
export type SourceHealthMatrix = z.infer<typeof SourceHealthMatrix>;

// -----------------------------------------------------------------
// Revision Timeline (vintage / as-known)
// -----------------------------------------------------------------

export const RevisionEvent = z.object({
  ts_utc: z.string(),
  source_id: z.string(),
  field_name: z.string().optional(),
  vintage_date: z.string(),
  revision_kind: z.enum(["INITIAL", "REVISED", "FINAL"]),
  prev_value: z.number().nullable().optional(),
  new_value: z.number().nullable().optional(),
  diff: z.number().nullable().optional(),
});
export type RevisionEvent = z.infer<typeof RevisionEvent>;

export const RevisionTimeline = z.object({
  field_name: z.string(),
  source_id: z.string(),
  as_known_series: z.array(z.object({ ts: z.string(), v: z.number().nullable() })),
  latest_series: z.array(z.object({ ts: z.string(), v: z.number().nullable() })),
  events: z.array(RevisionEvent),
});
export type RevisionTimeline = z.infer<typeof RevisionTimeline>;

// -----------------------------------------------------------------
// OpenLineage LLMProvenanceRunFacet
// -----------------------------------------------------------------

export const LLMProvenanceRunFacet = z.object({
  run_id: z.string(),
  job: z.string().optional(),
  inputs: z.array(z.string()).optional(),
  outputs: z.array(z.string()).optional(),
  facets: z.object({
    llm_provenance: z.object({
      model: z.string().optional(),
      prompt_version: z.string().optional(),
      schema_version: z.string().optional(),
      validation: z
        .object({
          status: z.enum(["PASSED", "REJECTED"]),
          rules: z.array(z.string()).optional(),
          final_confidence: z.number().optional(),
        })
        .optional(),
    }),
  }),
});
export type LLMProvenanceRunFacet = z.infer<typeof LLMProvenanceRunFacet>;

// -----------------------------------------------------------------
// SSE event
// -----------------------------------------------------------------

export const SSEEvent = z.object({
  id: z.string().optional(),
  event: z.string().optional(),
  data: z.union([z.string(), z.record(z.any())]).optional(),
});
export type SSEEvent = z.infer<typeof SSEEvent>;

// -----------------------------------------------------------------
// T-46 extended API types
// -----------------------------------------------------------------

export const TaskStatus = z.enum(["queued", "running", "done", "failed", "cancelled"]);
export type TaskStatus = z.infer<typeof TaskStatus>;

export const AsyncTask = z.object({
  job_id: z.string(),
  task_type: z.string(),
  status: TaskStatus,
  progress: z.number().min(0).max(100).optional(),
  message: z.string().optional(),
  created_at: z.string(),
  finished_at: z.string().optional(),
  result: z.record(z.any()).optional(),
  error: z.string().optional(),
});
export type AsyncTask = z.infer<typeof AsyncTask>;

export const PanelBuildRequest = z.object({
  symbols: z.array(z.string()).optional(),
  decision_time: z.string().optional(),
  force_rebuild: z.boolean().optional(),
});
export type PanelBuildRequest = z.infer<typeof PanelBuildRequest>;

export const ReportBuildRequest = z.object({
  panel_id: z.string().optional(),
  symbols: z.array(z.string()).optional(),
  language: z.string().default("zh"),
});
export type ReportBuildRequest = z.infer<typeof ReportBuildRequest>;

export const BacktestRunRequest = z.object({
  strategy: z.string(),
  symbols: z.array(z.string()).optional(),
  start_date: z.string().optional(),
  end_date: z.string().optional(),
  params: z.record(z.any()).optional(),
});
export type BacktestRunRequest = z.infer<typeof BacktestRunRequest>;

export const SyncRequest = z.object({
  symbols: z.array(z.string()).optional(),
  full_refresh: z.boolean().optional(),
});
export type SyncRequest = z.infer<typeof SyncRequest>;

export const SystemHealth = z.object({
  status: z.string(),
  version: z.string(),
  storage_backend: z.string().optional(),
  duckdb_version: z.string().optional(),
  panel_count: z.number().int().nonnegative().optional(),
  observation_count: z.number().int().nonnegative().optional(),
  uptime_seconds: z.number().optional(),
  sources: z.record(z.any()).optional(),
});
export type SystemHealth = z.infer<typeof SystemHealth>;

export const SnapshotDate = z.object({
  date: z.string(),
  row_count: z.number().int().nonnegative(),
  quality_score: z.number().optional(),
});
export type SnapshotDate = z.infer<typeof SnapshotDate>;

export const BacktestResult = z.object({
  total_return: z.number().optional(),
  sharpe_ratio: z.number().optional(),
  max_drawdown: z.number().optional(),
  win_rate: z.number().optional(),
  trade_count: z.number().int().optional(),
  equity_curve: z.array(z.object({ date: z.string(), value: z.number() })).optional(),
});
export type BacktestResult = z.infer<typeof BacktestResult>;

export const RegistryEntry = z.object({
  name: z.string(),
  type: z.string().optional(),
  asset_class: z.string().optional(),
  display_name_zh: z.string().optional(),
  source: z.string().optional(),
  status: z.string().optional(),
});
export type RegistryEntry = z.infer<typeof RegistryEntry>;

// -----------------------------------------------------------------
// Validation helpers
// -----------------------------------------------------------------

export const safeParse = <T extends z.ZodTypeAny>(
  schema: T,
  raw: unknown,
  context = "api",
): z.infer<T> | null => {
  const res = schema.safeParse(raw);
  if (!res.success) {
    if (typeof console !== "undefined") {
      console.warn(`[${context}] zod validation failed`, res.error.issues);
    }
    return null;
  }
  return res.data;
};
