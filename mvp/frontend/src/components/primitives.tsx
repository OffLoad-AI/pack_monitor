import type { ReactNode } from "react";
import type { Severity, StageStatus, Verdict } from "../api/types";
import {
  severityDot,
  severityLabel,
  severityStyle,
  stageStatusLabel,
  stageStatusStyle,
  verdictLabel,
  verdictStyle,
} from "../lib/meaning";

export function SeverityTag({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-2xs font-medium ${severityStyle[severity]}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${severityDot[severity]}`} />
      {severityLabel[severity]}
    </span>
  );
}

export function VerdictTag({
  verdict,
  size = "sm",
}: {
  verdict: Verdict | null;
  size?: "sm" | "lg";
}) {
  if (!verdict)
    return <span className="text-2xs text-ink-3">Not run</span>;
  const pad = size === "lg" ? "px-2.5 py-1 text-sm" : "px-1.5 py-0.5 text-2xs";
  return (
    <span
      className={`inline-block rounded border font-medium ${pad} ${verdictStyle[verdict]}`}
    >
      {verdictLabel[verdict]}
    </span>
  );
}

export function StatusTag({ status }: { status: StageStatus }) {
  return (
    <span
      className={`inline-block rounded border px-1.5 py-0.5 font-mono text-2xs ${stageStatusStyle[status]}`}
    >
      {stageStatusLabel[status]}
    </span>
  );
}

/** Every number in this interface is monospace and tabular. */
export function Mono({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={`font-mono tabular text-xs ${className}`}>{children}</span>
  );
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      <div className="h-8 w-8 rounded border border-dashed border-line-strong" />
      <div className="mt-1 text-sm font-medium text-ink">{title}</div>
      <div className="max-w-md text-sm text-ink-3">{detail}</div>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  const err = error as { message?: string; hint?: string };
  return (
    <div className="rounded border border-material-line bg-material-bg px-4 py-3">
      <div className="text-sm font-medium text-material">
        {err?.message ?? "Something went wrong."}
      </div>
      {err?.hint ? (
        <div className="mt-1 font-mono text-xs text-ink-2">{err.hint}</div>
      ) : null}
      {retry ? (
        <button className="btn-ghost btn-sm mt-2.5" onClick={retry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Skeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-px" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 animate-pulse bg-surface-sunk" />
      ))}
    </div>
  );
}

export function SectionTitle({
  children,
  right,
}: {
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line px-3.5 py-2">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-2">
        {children}
      </h2>
      {right}
    </div>
  );
}

/** A confidence bar. Neutral: confidence is not itself good or bad news. */
export function ConfidenceBar({ value }: { value: number | null }) {
  if (value === null || value === undefined)
    return <span className="text-2xs text-ink-4">n/a</span>;
  return (
    <span className="inline-flex items-center gap-1.5" title={`${value}`}>
      <span className="h-1 w-16 overflow-hidden rounded-full bg-surface-sunk">
        <span
          className="block h-full bg-ink-3"
          style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` }}
        />
      </span>
      <span className="font-mono tabular text-2xs text-ink-2">
        {value.toFixed(2)}
      </span>
    </span>
  );
}
