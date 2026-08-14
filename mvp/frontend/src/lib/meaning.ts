import type { Severity, StageName, StageStatus, Verdict } from "../api/types";

/**
 * Colour is the interface's only signal, so it is defined once, here, and
 * nowhere else. Extended from the version-identification build rather than
 * replaced: verdict, severity and diff add/remove are the only things that get a
 * hue, and everything else stays neutral.
 */

export const SEVERITY_ORDER: Severity[] = ["MATERIAL", "UNCERTAIN", "COSMETIC", "NONE"];

export const severityStyle: Record<Severity, string> = {
  MATERIAL: "text-material bg-material-bg border-material-line",
  COSMETIC: "text-cosmetic bg-cosmetic-bg border-cosmetic-line",
  UNCERTAIN: "text-uncertain bg-uncertain-bg border-uncertain-line",
  NONE: "text-ink-3 bg-surface-sunk border-line",
};

export const severityDot: Record<Severity, string> = {
  MATERIAL: "bg-material",
  COSMETIC: "bg-cosmetic",
  UNCERTAIN: "bg-uncertain",
  NONE: "bg-ink-4",
};

/** Region outlines drawn over an image. Same hues, as stroke colours. */
export const severityStroke: Record<Severity, string> = {
  MATERIAL: "#c0392f",
  COSMETIC: "#9a6208",
  UNCERTAIN: "#5b4bab",
  NONE: "#697585",
};

export const severityLabel: Record<Severity, string> = {
  MATERIAL: "Material",
  COSMETIC: "Cosmetic",
  UNCERTAIN: "Uncertain",
  NONE: "No difference",
};

export const verdictStyle: Record<Verdict, string> = {
  IDENTICAL: "text-clear bg-clear-bg border-clear-line",
  MATCH: "text-clear bg-clear-bg border-clear-line",
  MATCH_WITH_COSMETIC_DIFFERENCES: "text-cosmetic bg-cosmetic-bg border-cosmetic-line",
  DIFFERENT: "text-material bg-material-bg border-material-line",
  NEEDS_REVIEW: "text-uncertain bg-uncertain-bg border-uncertain-line",
  CANNOT_COMPARE: "text-ink-2 bg-surface-sunk border-line-strong",
};

/**
 * Named by what the reader needs to know, in sentence case and active voice.
 * `CANNOT_COMPARE` is not "error" — it is a designed outcome, and calling it a
 * failure would teach people to distrust the one answer that is always honest.
 */
export const verdictLabel: Record<Verdict, string> = {
  IDENTICAL: "Identical file",
  MATCH: "Artwork matches",
  MATCH_WITH_COSMETIC_DIFFERENCES: "Matches, with cosmetic differences",
  DIFFERENT: "Artwork differs",
  NEEDS_REVIEW: "Needs review",
  CANNOT_COMPARE: "Couldn't align these images",
};

export const verdictHint: Record<Verdict, string> = {
  IDENTICAL:
    "The two files are byte for byte the same file. This is proof, not an estimate.",
  MATCH:
    "Nothing beyond re-encoding separates these two images. The artwork is the same.",
  MATCH_WITH_COSMETIC_DIFFERENCES:
    "The pack says the same thing. What differs is how it is written or coloured, not what it claims.",
  DIFFERENT:
    "At least one difference changes what the pack says — a value, a unit or a claim.",
  NEEDS_REVIEW:
    "Something differs, but not in a way this tool can settle on its own. A person needs to look.",
  CANNOT_COMPARE:
    "Not enough matching detail was found to line the two images up. This usually means they show different products, or one is too low-resolution.",
};

export const stageLabel: Record<StageName, string> = {
  load_normalize: "Load and clean up",
  hash: "Compare the files",
  registration: "Line the images up",
  structural_diff: "Find what changed",
  region_ocr: "Read both sides",
  text_compare: "Compare the text",
  verdict: "Decide",
  pipeline: "Pipeline",
};

export const stagePurpose: Record<StageName, string> = {
  load_normalize:
    "Undo what the marketplace did that isn't a real difference: padding, colour profile, transparency.",
  hash: "If the files are byte-identical, nothing else needs checking.",
  registration:
    "Find matching landmarks in both images and work out the transform that puts one on top of the other.",
  structural_diff:
    "Compare local structure, not raw pixels, and propose regions worth reading.",
  region_ocr: "Read the text on both sides of each proposed region.",
  text_compare:
    "Align the readings word by word and classify each difference by what kind it is.",
  verdict: "Reduce everything above to one answer.",
  pipeline: "",
};

export const stageStatusStyle: Record<StageStatus, string> = {
  OK: "text-clear bg-clear-bg border-clear-line",
  DEGRADED: "text-cosmetic bg-cosmetic-bg border-cosmetic-line",
  FAILED: "text-material bg-material-bg border-material-line",
  SKIPPED: "text-ink-3 bg-surface-sunk border-line",
};

export const stageStatusLabel: Record<StageStatus, string> = {
  OK: "OK",
  DEGRADED: "Degraded",
  FAILED: "Stopped",
  SKIPPED: "Skipped",
};

/** What each kind of difference is, in the reader's words. */
export const differenceLabel: Record<string, string> = {
  NUMBER_CHANGED: "Value changed",
  NUMBER_AND_UNIT_CHANGED: "Value and unit changed",
  NUMBER_FORMAT: "Same value, written differently",
  TEXT_ADDED: "Text added",
  TEXT_REMOVED: "Text removed",
  TEXT_CHANGED: "Wording changed",
  CONFUSABLE_CHARACTERS: "Possibly a misreading",
  OCR_UNRELIABLE: "Could not be read reliably",
  PUNCTUATION_ONLY: "Punctuation only",
  VISUAL_ONLY: "Visual change, no text",
  PALETTE_SHIFT: "Pack recoloured",
  NO_DIFFERENCE: "No difference in the text",
};

/** Metrics whose names would otherwise be read as jargon. */
export const metricLabel: Record<string, string> = {
  inliers: "Agreeing points",
  inlier_ratio: "Share of matches agreeing",
  matches_raw: "Candidate matches",
  matches_after_ratio: "Matches after filtering",
  keypoints_ref: "Landmarks, reference",
  keypoints_mkt: "Landmarks, marketplace",
  mean_reprojection_error: "Average alignment error (px)",
  condition_number: "Transform conditioning",
  implied_scale: "Implied resize",
  implied_rotation_deg: "Implied rotation (°)",
  overlap_fraction: "Shared area",
  global_ssim: "Structural similarity",
  mean_ssim_in_overlap: "Structural similarity, shared area",
  changed_area_fraction: "Share of area changed",
  changed_spread_fraction: "Reach of the change",
  chroma_dominant_fraction: "Share that is colour, not shape",
  regions_before_filter: "Blobs found",
  regions_after_filter: "Regions kept",
  threshold_used: "Structure threshold",
  chroma_threshold_used: "Colour threshold",
  regions_read: "Regions read",
  regions_with_text: "Regions containing text",
  regions_ocr_unreliable: "Regions read unreliably",
  mean_token_confidence: "Average reading confidence",
  ocr_calls: "Reading passes",
  reference_sha256: "Reference fingerprint",
  marketplace_sha256: "Marketplace fingerprint",
};

/** Metrics too large or too structural to belong in a table. */
export const HIDDEN_METRICS = new Set(["homography", "comparisons", "error"]);

export function formatMetric(key: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.join(" x ");
  if (typeof value === "number") {
    if (Number.isInteger(value)) return String(value);
    if (key.endsWith("_fraction") || key === "inlier_ratio")
      return `${(value * 100).toFixed(2)}%`;
    return value.toFixed(4);
  }
  return String(value);
}
