import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { EmptyState, ErrorState, Mono, Skeleton } from "../components/primitives";
import { elapsedSeconds, formatDateTime, formatDuration, percent } from "../lib/format";

const STATUS_STYLE: Record<string, string> = {
  RUNNING: "text-ink border-line bg-surface-sunk",
  COMPLETE: "text-clear border-clear-line bg-clear-bg",
  FAILED: "text-material border-material-line bg-material-bg",
};

export function Runs() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });

  if (runs.isLoading) return <div className="p-4"><Skeleton rows={8} /></div>;
  if (runs.isError)
    return (
      <div className="p-4">
        <ErrorState error={runs.error} retry={() => runs.refetch()} />
      </div>
    );

  if (!runs.data?.length)
    return (
      <div className="p-4">
        <div className="panel">
          <EmptyState
            title="No runs yet"
            detail="Start one from the dashboard, or run: python -m pipeline.run --input ./data/corpus/scraped/run_2026_01"
            action={
              <Link to="/" className="btn-primary">
                Go to dashboard
              </Link>
            }
          />
        </div>
      </div>
    );

  return (
    <div className="p-4">
      <h1 className="mb-3 text-lg font-semibold tracking-tight">Run history</h1>
      <div className="panel overflow-hidden">
        <table className="dense-table">
          <thead>
            <tr>
              <th className="w-16">Run</th>
              <th className="w-24">Status</th>
              <th className="w-36">Started</th>
              <th className="w-20 text-right">Duration</th>
              <th className="w-24 text-right">Images</th>
              <th className="w-20 text-right">Cached</th>
              <th className="w-20 text-right">Stale</th>
              <th className="w-20 text-right">Current</th>
              <th className="w-24 text-right">Unidentified</th>
              <th>Input</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.map((r) => (
              <tr key={r.id}>
                <td>
                  <Link to={`/runs/${r.id}`} className="font-mono text-xs hover:underline">
                    #{r.id}
                  </Link>
                </td>
                <td>
                  <span
                    className={`rounded border px-1.5 py-0.5 text-2xs font-medium ${
                      STATUS_STYLE[r.status] ?? ""
                    }`}
                  >
                    {r.status.toLowerCase()}
                  </span>
                </td>
                <td className="text-xs text-ink-2">{formatDateTime(r.started_at)}</td>
                <td className="text-right">
                  <Mono>
                    {formatDuration(elapsedSeconds(r.started_at, r.finished_at))}
                  </Mono>
                </td>
                <td className="text-right">
                  <Mono>{r.images_total.toLocaleString()}</Mono>
                </td>
                <td className="text-right">
                  <Mono className="text-ink-3">
                    {percent(r.images_cached, r.images_total, 0)}
                  </Mono>
                </td>
                <td className="text-right">
                  <Mono className={r.counts.STALE_VERSION ? "text-material" : ""}>
                    {r.counts.STALE_VERSION ?? 0}
                  </Mono>
                </td>
                <td className="text-right">
                  <Mono className="text-clear">{r.counts.PASS ?? 0}</Mono>
                </td>
                <td className="text-right">
                  <Mono className={r.counts.UNKNOWN_IMAGE ? "text-uncertain" : ""}>
                    {r.counts.UNKNOWN_IMAGE ?? 0}
                  </Mono>
                </td>
                <td>
                  <Mono className="text-ink-3">{r.input_dir}</Mono>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
