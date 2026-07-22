// API types — mirrors config/schemas/*.schema.json (PRD §12).

export type QualityStatus =
  | "VALID"
  | "DEGRADED"
  | "STALE"
  | "PARTIAL"
  | "REJECTED"
  | "INFERRED_AVAILABILITY"
  | "SOURCE_FAILED"
  | "SOURCE_THROTTLED";

export type FieldState =
  | "LOW_EXTREME"
  | "LOW"
  | "NEUTRAL"
  | "HIGH"
  | "HIGH_EXTREME"
  | "MISSING"
  | "STALE"
  | "INFERRED_AVAILABILITY";

export interface PanelSummary {
  panel_id: string;
  panel_sha256: string;
  decision_time: string;
  panel_version: string;
  feature_version: string;
  quality_status: QualityStatus;
  quality_score: number;
  row_count: number;
  field_count: number;
  instrument_registry_version: string;
  metric_registry_version: string;
}

export interface SlicePoint {
  timestamp: string;
  [field: string]: string | number | string[] | null;
}

export interface SliceDataset {
  slice_id: string;
  panel_id: string;
  fields: string[];
  points: SlicePoint[];
}

export interface Evidence {
  evidence_id: string;
  symbol: string;
  field_name: string;
  display_name_zh: string;
  value: number;
  unit: string;
  state: FieldState;
  observation_time: string;
  available_at: string;
  age_hours: number;
  source_name: string;
  dataset_name: string;
  feature_observation_id: string;
  normalized_observation_id: string;
  raw_record_hash: string;
  feature_definition_id: string;
  quality_status: QualityStatus;
  semantic_caveat_zh: string;
}

export interface Finding {
  finding_id: string;
  title_zh: string;
  claim_zh: string;
  classification: string;
  support_type: string;
  causal_language_level: "ASSOCIATIVE_ONLY" | "DESCRIPTIVE";
  llm_confidence: number;
  final_confidence: number;
  evidence_ids: string[];
  limitations_zh: string[];
  model?: string;
  prompt_version?: string;
}
