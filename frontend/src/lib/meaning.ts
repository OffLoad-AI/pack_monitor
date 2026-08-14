import type { MatchMethod, Severity, Verdict } from "../api/types";

/**
 * Colour is the interface's only signal, so it is defined once, here, and
 * nowhere else. Severity and verdict are the only things that get a hue.
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

export const verdictStyle: Record<Verdict, string> = {
  STALE_VERSION: "text-material bg-material-bg border-material-line",
  UNKNOWN_IMAGE: "text-uncertain bg-uncertain-bg border-uncertain-line",
  ERROR: "text-material bg-material-bg border-material-line",
  PASS: "text-clear bg-clear-bg border-clear-line",
};

/** Names things by what the user controls, not by how the system works. */
export const verdictLabel: Record<Verdict, string> = {
  STALE_VERSION: "Stale artwork",
  UNKNOWN_IMAGE: "Not identified",
  ERROR: "Failed",
  PASS: "Current",
};

export const severityLabel: Record<Severity, string> = {
  MATERIAL: "Material",
  COSMETIC: "Cosmetic",
  UNCERTAIN: "Uncertain",
  NONE: "None",
};

export const methodLabel: Record<MatchMethod, string> = {
  HASH_EXACT: "Exact file match",
  PIXEL_DIFF: "Pixel difference",
  REGION_CHECK: "Region check",
  CACHED: "Unchanged since last run",
  NONE: "No match",
};

export const methodHint: Record<MatchMethod, string> = {
  HASH_EXACT:
    "The listing is serving this artwork file byte for byte. This is proof, not an estimate.",
  PIXEL_DIFF:
    "Exactly one artwork version differs from this listing image by no more than compression noise.",
  REGION_CHECK:
    "Versions look alike overall, so they were compared inside the regions known to differ between them.",
  CACHED: "The file and the approved artwork are both unchanged since the last run.",
  NONE: "No approved artwork explains this image.",
};

export const editTypeLabel: Record<string, string> = {
  NUMERIC_DRIFT: "Value changed",
  CLAIM_REMOVED: "Claim removed",
  CLAIM_ADDED: "Claim added",
  CERT_REMOVED: "Certification removed",
  WEIGHT_CHANGE: "Net weight changed",
  PALETTE_SHIFT: "Palette shifted",
  LOGO_NUDGE: "Logo moved",
  NO_CHANGE: "No change",
};

export function fieldLabel(key: string | null): string {
  if (!key) return "Unmapped region";
  return key
    .replace(/_/g, " ")
    .replace(/\bmg\b/, "(mg)")
    .replace(/\bg\b$/, "(g)")
    .replace(/\bkcal\b/, "(kcal)")
    .replace(/^\w/, (c) => c.toUpperCase());
}
