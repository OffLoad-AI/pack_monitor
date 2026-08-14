import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fileUrl } from "../api/client";
import type { Verdict } from "../api/types";
import {
  EmptyState,
  ErrorState,
  Mono,
  SeverityTag,
  Skeleton,
  VerdictTag,
} from "../components/primitives";
import { verdictLabel } from "../lib/meaning";

const VERDICTS: Verdict[] = [
  "IDENTICAL",
  "MATCH",
  "MATCH_WITH_COSMETIC_DIFFERENCES",
  "DIFFERENT",
  "NEEDS_REVIEW",
  "CANNOT_COMPARE",
];

/**
 * A log, not a work queue. There is no bulk selection, no acknowledgement and no
 * sort — this build has no review workflow, and giving it the furniture of one
 * would suggest a process that does not exist.
 */
export function History() {
  const [filters, setFilters] = useState<Verdict[]>([]);
  const queryClient = useQueryClient();

  const list = useQuery({
    queryKey: ["comparisons", filters],
    queryFn: () => api.list(filters),
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (c) => c.status === "RUNNING" || c.status === "QUEUED",
      )
        ? 1500
        : false,
  });

  const remove = useMutation({
    mutationFn: api.remove,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["comparisons"] }),
  });

  const toggle = (v: Verdict) =>
    setFilters((f) => (f.includes(v) ? f.filter((x) => x !== v) : [...f, v]));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold text-ink">History</h1>
        <span className="text-xs text-ink-3">
          {list.data ? `${list.data.total} comparison${list.data.total === 1 ? "" : "s"}` : ""}
        </span>
        <div className="ml-auto flex flex-wrap gap-1">
          {VERDICTS.map((v) => (
            <button
              key={v}
              onClick={() => toggle(v)}
              aria-pressed={filters.includes(v)}
              className={`rounded border px-2 py-0.5 text-2xs transition-colors ${
                filters.includes(v)
                  ? "border-ink bg-ink text-white"
                  : "border-line bg-surface text-ink-3 hover:text-ink"
              }`}
            >
              {verdictLabel[v]}
            </button>
          ))}
        </div>
      </div>

      {list.isLoading ? <Skeleton rows={8} /> : null}
      {list.isError ? (
        <ErrorState error={list.error} retry={() => list.refetch()} />
      ) : null}

      {list.data && !list.data.items.length ? (
        <div className="rounded border border-line bg-surface">
          <EmptyState
            title={filters.length ? "Nothing matches those filters" : "No comparisons yet"}
            detail={
              filters.length
                ? "Clear a filter to see the rest."
                : "Drop a reference and a marketplace image on the Compare screen to run the first one."
            }
            action={
              filters.length ? (
                <button className="btn-ghost btn-sm" onClick={() => setFilters([])}>
                  Clear filters
                </button>
              ) : (
                <Link className="btn-primary btn-sm" to="/">
                  Compare a pair
                </Link>
              )
            }
          />
        </div>
      ) : null}

      {list.data?.items.length ? (
        <div className="overflow-x-auto rounded border border-line bg-surface">
          <table className="dense-table">
            <thead>
              <tr>
                <th className="w-14">Pair</th>
                <th>Label</th>
                <th>Verdict</th>
                <th>Worst difference</th>
                <th className="text-right">Regions</th>
                <th className="text-right">Confidence</th>
                <th className="text-right">Time</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link
                      to={`/comparisons/${c.id}`}
                      className="flex items-center gap-1"
                      aria-label={`Comparison ${c.id}`}
                    >
                      <Thumb src={fileUrl(c.reference_image)} />
                      <Thumb src={fileUrl(c.marketplace_image)} />
                    </Link>
                  </td>
                  <td>
                    <Link
                      to={`/comparisons/${c.id}`}
                      className="text-ink hover:underline"
                    >
                      {c.label || <span className="text-ink-4">#{c.id}</span>}
                    </Link>
                  </td>
                  <td>
                    {c.status === "RUNNING" || c.status === "QUEUED" ? (
                      <span className="text-2xs text-ink-3">running…</span>
                    ) : (
                      <VerdictTag verdict={c.verdict} />
                    )}
                  </td>
                  <td>
                    {c.worst_severity !== "NONE" ? (
                      <SeverityTag severity={c.worst_severity} />
                    ) : (
                      <span className="text-2xs text-ink-4">—</span>
                    )}
                  </td>
                  <td className="text-right">
                    <Mono>{c.region_count}</Mono>
                  </td>
                  <td className="text-right">
                    <Mono>{c.confidence.toFixed(2)}</Mono>
                  </td>
                  <td className="text-right">
                    <Mono className="text-ink-3">
                      {(c.duration_ms / 1000).toFixed(1)}s
                    </Mono>
                  </td>
                  <td>
                    <button
                      className="text-ink-4 hover:text-material"
                      title="Delete this comparison and its artefacts"
                      aria-label={`Delete comparison ${c.id}`}
                      onClick={() => remove.mutate(c.id)}
                    >
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function Thumb({ src }: { src?: string }) {
  return src ? (
    <img
      src={src}
      alt=""
      loading="lazy"
      className="h-7 w-7 rounded-sm border border-line object-cover"
    />
  ) : (
    <span className="h-7 w-7 rounded-sm border border-dashed border-line" />
  );
}
