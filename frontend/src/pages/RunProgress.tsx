import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Finding, Run } from "../api/types";
import {
  EmptyState,
  ErrorState,
  Mono,
  SectionTitle,
  SeverityTag,
  Skeleton,
  Stat,
  VerdictTag,
} from "../components/primitives";
import { elapsedSeconds, formatDateTime, formatDuration, percent } from "../lib/format";

export function RunProgress() {
  const { id } = useParams();
  const runId = Number(id);
  const qc = useQueryClient();
  const [live, setLive] = useState<Run | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId) });

  // Server-sent events, so the queue can be worked while the run is still going.
  useEffect(() => {
    const es = new EventSource(`/api/runs/${runId}/progress`);
    esRef.current = es;
    es.addEventListener("progress", (e) => {
      setLive(JSON.parse((e as MessageEvent).data));
    });
    es.addEventListener("done", (e) => {
      setLive(JSON.parse((e as MessageEvent).data));
      qc.invalidateQueries({ queryKey: ["stats"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      es.close();
    });
    es.onerror = () => es.close();
    return () => es.close();
  }, [runId, qc]);

  const current = live ?? run.data;

  const findings = useQuery({
    queryKey: ["run-findings-live", runId, current?.images_processed],
    queryFn: () =>
      api.findings(runId, {
        verdict: ["STALE_VERSION", "UNKNOWN_IMAGE", "ERROR"],
        sort: "id",
        order: "desc",
        limit: 25,
      }),
    enabled: !!current,
  });

  if (run.isLoading && !current) return <div className="p-4"><Skeleton rows={8} /></div>;
  if (run.isError)
    return (
      <div className="p-4">
        <ErrorState error={run.error} retry={() => run.refetch()} />
      </div>
    );

  const r = current!;
  const elapsed = elapsedSeconds(r.started_at, r.finished_at);
  const rate = elapsed > 0 ? r.images_processed / elapsed : 0;
  const remaining = rate > 0 ? (r.images_total - r.images_processed) / rate : 0;
  const pct = r.images_total ? (r.images_processed / r.images_total) * 100 : 0;

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Run {r.id}</h1>
          <p className="text-xs text-ink-3">
            {formatDateTime(r.started_at)} · pipeline {r.pipeline_version} ·{" "}
            <span className="font-mono">{r.input_dir}</span>
          </p>
        </div>
        <Link to={`/queue?run=${r.id}`} className="btn-ghost">
          Review findings from this run
        </Link>
      </div>

      {r.status === "FAILED" ? (
        <ErrorState
          error={{
            message: "This run did not finish.",
            hint: r.error ?? undefined,
          }}
        />
      ) : null}

      <div className="panel px-3.5 py-3">
        <div className="flex items-baseline justify-between">
          <span className="text-sm font-medium">
            {r.status === "RUNNING" ? "Processing" : "Complete"}
          </span>
          <span className="font-mono tabular text-sm">
            {r.images_processed.toLocaleString()} / {r.images_total.toLocaleString()}
          </span>
        </div>
        <div
          className="mt-2 h-1.5 w-full overflow-hidden rounded bg-surface-sunk"
          role="progressbar"
          aria-valuenow={Math.round(pct)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full bg-ink transition-[width] duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 font-mono tabular text-2xs text-ink-3">
          <span>{pct.toFixed(1)}%</span>
          <span>{rate.toFixed(1)} images/s</span>
          <span>elapsed {formatDuration(elapsed)}</span>
          {r.status === "RUNNING" ? (
            <span>about {formatDuration(remaining)} left</span>
          ) : null}
          <span>
            cache {percent(r.images_cached, r.images_total, 0)} (
            {r.images_cached.toLocaleString()})
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Stale artwork" value={r.counts.STALE_VERSION ?? 0} tone="material" />
        <Stat label="Current" value={r.counts.PASS ?? 0} tone="clear" />
        <Stat label="Not identified" value={r.counts.UNKNOWN_IMAGE ?? 0} tone="uncertain" />
        <Stat label="Failed" value={r.counts.ERROR ?? 0} tone={r.counts.ERROR ? "material" : "neutral"} />
      </div>

      <div className="panel">
        <SectionTitle
          right={
            <span className="text-2xs text-ink-3">
              {r.status === "RUNNING" ? "updating live" : "most recent"}
            </span>
          }
        >
          Findings as they appear
        </SectionTitle>
        {findings.isLoading ? (
          <Skeleton rows={8} />
        ) : !findings.data?.items.length ? (
          <EmptyState
            title="No problems found yet"
            detail={
              r.status === "RUNNING"
                ? "Findings appear here as images are processed."
                : "Every listing in this run serves its approved artwork."
            }
          />
        ) : (
          <table className="dense-table">
            <thead>
              <tr>
                <th className="w-12">Image</th>
                <th>Product</th>
                <th className="w-28">Verdict</th>
                <th className="w-24">Severity</th>
                <th className="w-32">Serving → approved</th>
                <th className="w-16 text-right">Regions</th>
              </tr>
            </thead>
            <tbody>
              {findings.data.items.map((f: Finding) => (
                <tr key={f.id}>
                  <td>
                    {f.thumb_url ? (
                      <img
                        src={f.thumb_url}
                        alt=""
                        loading="lazy"
                        className="h-8 w-8 rounded border border-line object-cover"
                      />
                    ) : null}
                  </td>
                  <td>
                    <Link to={`/findings/${f.id}`} className="hover:underline">
                      {f.product_name}
                    </Link>
                    <Mono className="ml-2 text-ink-3">{f.product_id}</Mono>
                  </td>
                  <td>
                    <VerdictTag verdict={f.verdict} />
                  </td>
                  <td>
                    <SeverityTag severity={f.severity} />
                  </td>
                  <td>
                    <Mono>
                      {f.matched_version ?? "—"}
                      <span className="mx-1 text-ink-4">→</span>
                      {f.current_version ?? "—"}
                    </Mono>
                  </td>
                  <td className="text-right">
                    <Mono>{f.region_count || "—"}</Mono>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
