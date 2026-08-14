export type Verdict = "PASS" | "STALE_VERSION" | "UNKNOWN_IMAGE" | "ERROR";
export type Severity = "MATERIAL" | "COSMETIC" | "UNCERTAIN" | "NONE";
export type MatchMethod =
  | "HASH_EXACT"
  | "PIXEL_DIFF"
  | "REGION_CHECK"
  | "CACHED"
  | "NONE";

export interface Version {
  id: number;
  product_id: string;
  version_label: string;
  sha256: string;
  width: number;
  height: number;
  is_current: boolean;
  approved_at: string;
  image_url: string | null;
  thumb_url: string | null;
}

export interface Product {
  id: string;
  name: string;
  brand: string;
  version_count: number;
  current_version: Version | null;
  last_verdict: Verdict | null;
  last_severity: Severity | null;
  open_findings: number;
}

export interface Region {
  x: number;
  y: number;
  w: number;
  h: number;
  scraped_box: [number, number, number, number] | null;
  field_key: string | null;
  old: string | null;
  new: string | null;
  severity: Severity;
  edit_type: string | null;
  from_version: string | null;
  to_version: string | null;
  region_signature: string | null;
  acknowledged: boolean;
  note: string | null;
}

export interface Finding {
  id: number;
  run_id: number;
  product_id: string;
  product_name: string | null;
  verdict: Verdict;
  severity: Severity;
  match_method: MatchMethod;
  confidence: number;
  matched_version: string | null;
  current_version: string | null;
  matched_version_id: number | null;
  current_version_id: number | null;
  region_count: number;
  acknowledged: boolean;
  created_at: string;
  thumb_url: string | null;
  source_name: string | null;
}

export interface FindingDetail extends Finding {
  regions: Region[];
  source_path: string;
  width: number;
  height: number;
  error: string | null;
  version_chain: string[];
}

export interface FindingImages {
  scraped_url: string | null;
  matched_url: string | null;
  current_url: string | null;
  diff_overlay_url: string | null;
  scraped_size: [number, number] | null;
  matched_size: [number, number] | null;
}

export interface Run {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: "RUNNING" | "COMPLETE" | "FAILED";
  pipeline_version: string;
  input_dir: string;
  images_total: number;
  images_processed: number;
  images_cached: number;
  error: string | null;
  counts: Partial<Record<Verdict, number>>;
  severity_counts: Partial<Record<Severity, number>>;
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface Stats {
  products: number;
  versions: number;
  latest_run: {
    id: number;
    status: string;
    started_at: string;
    finished_at: string | null;
    images_total: number;
    images_processed: number;
    images_cached: number;
  } | null;
  verdicts: Partial<Record<Verdict, number>>;
  severities: Partial<Record<Severity, number>>;
  awaiting_review: number;
  trend: {
    run_id: number;
    started_at: string;
    stale: number;
    pass: number;
    unknown: number;
    error: number;
    material: number;
  }[];
}

export interface Thresholds {
  values: Record<string, number | boolean | string>;
  calibration: Record<string, any> | null;
  chart_url: string | null;
}

export interface ProductDetail {
  id: string;
  name: string;
  brand: string;
  created_at: string;
  versions: Version[];
  findings: {
    id: number;
    run_id: number;
    verdict: Verdict;
    severity: Severity;
    match_method: MatchMethod;
    confidence: number;
    matched_version: string | null;
    current_version: string | null;
    region_count: number;
    acknowledged: boolean;
    created_at: string;
  }[];
}
