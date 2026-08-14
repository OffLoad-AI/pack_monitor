export type Verdict =
  | "IDENTICAL"
  | "MATCH"
  | "MATCH_WITH_COSMETIC_DIFFERENCES"
  | "DIFFERENT"
  | "NEEDS_REVIEW"
  | "CANNOT_COMPARE";

export type Severity = "MATERIAL" | "UNCERTAIN" | "COSMETIC" | "NONE";

export type StageStatus = "OK" | "DEGRADED" | "FAILED" | "SKIPPED";

export type StageName =
  | "load_normalize"
  | "hash"
  | "registration"
  | "structural_diff"
  | "region_ocr"
  | "text_compare"
  | "verdict"
  | "pipeline";

export interface Stage {
  stage: StageName;
  ordinal: number;
  status: StageStatus;
  confidence: number | null;
  duration_ms: number;
  metrics: Record<string, any>;
  artifacts: Record<string, string>;
  notes: string[];
}

export interface Region {
  id: number;
  ordinal: number;
  x: number;
  y: number;
  w: number;
  h: number;
  area_fraction: number;
  reference_text: string | null;
  marketplace_text: string | null;
  ocr_reliable: boolean;
  difference_type: string;
  severity: Severity;
  detail: string;
  ref_crop_path: string | null;
  mkt_crop_path: string | null;
  signal: number;
}

export interface Comparison {
  id: number;
  label: string | null;
  reference_path: string;
  marketplace_path: string;
  reference_sha256: string | null;
  marketplace_sha256: string | null;
  verdict: Verdict | null;
  confidence: number;
  status: "QUEUED" | "RUNNING" | "COMPLETE" | "FAILED";
  error: string | null;
  duration_ms: number;
  pipeline_version: string;
  created_at: string;
  region_count: number;
  worst_severity: Severity;
  reference_image: string | null;
  marketplace_image: string | null;
}

export interface ComparisonDetail extends Comparison {
  config: Record<string, any>;
  stages: Stage[];
  regions: Region[];
}

export interface Page<T> {
  total: number;
  offset: number;
  limit: number;
  items: T[];
}

export interface Created {
  id: number;
  status: string;
}

export interface BatchCreated {
  created: Created[];
  unmatched: string[];
}

export interface Config {
  values: Record<string, number | string>;
  editable: string[];
  calibrated: boolean;
  calibration: Record<string, any> | null;
  ocr_backends: string[];
  ocr_active: string;
}

export interface Progress {
  id: number;
  status: string;
  verdict: Verdict | null;
  confidence: number;
  expected_stages: StageName[];
  completed: {
    stage: StageName;
    status: StageStatus;
    duration_ms: number;
    confidence: number | null;
    notes: string[];
  }[];
}
