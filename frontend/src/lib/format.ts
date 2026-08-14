export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function elapsedSeconds(start: string, end?: string | null): number {
  const a = new Date(start).getTime();
  const b = end ? new Date(end).getTime() : Date.now();
  return (b - a) / 1000;
}

export function percent(n: number, d: number, digits = 0): string {
  if (!d) return "—";
  return `${((100 * n) / d).toFixed(digits)}%`;
}

export function shortHash(sha: string | null | undefined, n = 10): string {
  return sha ? sha.slice(0, n) : "—";
}

export function compactNumber(n: number): string {
  return n.toLocaleString();
}
