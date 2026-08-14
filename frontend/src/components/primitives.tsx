import type { ReactNode } from "react";
import type { MatchMethod, Severity, Verdict } from "../api/types";
import {
  methodLabel,
  severityDot,
  severityLabel,
  severityStyle,
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

export function VerdictTag({ verdict }: { verdict: Verdict }) {
  return (
    <span
      className={`inline-block rounded border px-1.5 py-0.5 text-2xs font-medium ${verdictStyle[verdict]}`}
    >
      {verdictLabel[verdict]}
    </span>
  );
}

export function MethodTag({ method }: { method: MatchMethod }) {
  return (
    <span className="font-mono text-2xs text-ink-3">{methodLabel[method]}</span>
  );
}

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

export function Stat({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "neutral" | "material" | "cosmetic" | "uncertain" | "clear";
}) {
  const toneClass = {
    neutral: "text-ink",
    material: "text-material",
    cosmetic: "text-cosmetic",
    uncertain: "text-uncertain",
    clear: "text-clear",
  }[tone];
  return (
    <div className="panel px-3.5 py-3">
      <div className="text-2xs font-medium uppercase tracking-wide text-ink-3">
        {label}
      </div>
      <div className={`mt-1 font-mono tabular text-2xl leading-none ${toneClass}`}>
        {value}
      </div>
      {sub ? <div className="mt-1.5 text-xs text-ink-3">{sub}</div> : null}
    </div>
  );
}

/** Empty states tell the user what to do next, not just that there is nothing. */
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
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <div className="h-8 w-8 rounded border border-dashed border-line-strong" />
      <div className="mt-1 text-sm font-medium text-ink">{title}</div>
      <div className="max-w-md text-sm text-ink-3">{detail}</div>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/** Errors say what happened and how to fix it. */
export function ErrorState({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  const err = error as { message?: string; hint?: string; status?: number };
  return (
    <div className="panel border-material-line bg-material-bg px-4 py-3">
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
