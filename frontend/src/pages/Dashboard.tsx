import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, ApiError } from "../api/client";
import { EmptyState, ErrorState, SectionTitle, Skeleton, Stat } from "../components/primitives";
import { useToast } from "../components/Toast";
import { formatDateTime, percent } from "../lib/format";

const DEFAULT_INPUT = "data/corpus/scraped/run_2026_01";

export function Dashboard() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { notify } = useToast();
  const [inputDir, setInputDir] = useState(DEFAULT_INPUT);

  const stats = useQuery({
    queryKey: ["stats"],
    queryFn: api.stats,
    refetchInterval: (q) =>
      q.state.data?.latest_run?.status === "RUNNING" ? 1000 : 20_000,
  });

  const start = useMutation({
    mutationFn: () => api.startRun(inputDir),
    onSuccess: (run) => {
      notify(`Run ${run.id} started`);
      qc.invalidateQueries({ queryKey: ["stats"] });
      navigate(`/runs/${run.id}`);
    },
    onError: (e: ApiError) => notify(e.message, "error"),
  });

  if (stats.isLoading) {
    return (
      <div className="p-4">
        <Skeleton rows={8} />
      </div>
    );
  }
  if (stats.isError) {
    return (
      <div className="p-4">
        <ErrorState error={stats.error} retry={() => stats.refetch()} />
      </div>
    );
  }

  const s = stats.data!;
  const run = s.latest_run;
  const v = s.verdicts;
  const total = Object.values(v).reduce((a, b) => a + (b ?? 0), 0);

  if (!run) {
    return (
      <div className="p-4">
        <div className="panel">
          <EmptyState
            title="No runs yet"
            detail={
              <>
                Point the monitor at a directory of listing images and start a run.
                The demo corpus lives at{" "}
                <code className="font-mono text-xs">{DEFAULT_INPUT}</code>.
              </>
            }
            action={
              <div className="flex items-center gap-2">
                <input
                  className="field w-72 font-mono text-xs"
                  value={inputDir}
                  onChange={(e) => setInputDir(e.target.value)}
                  aria-label="Input directory"
                />
                <button
                  className="btn-primary"
                  onClick={() => start.mutate()}
                  disabled={start.isPending}
                >
                  {start.isPending ? "Starting…" : "Start run"}
                </button>
              </div>
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Latest run</h1>
          <p className="text-xs text-ink-3">
            Run {run.id} · started {formatDateTime(run.started_at)} ·{" "}
            {run.status === "RUNNING" ? (
              <span className="font-medium text-ink">in progress</span>
            ) : (
              `finished ${formatDateTime(run.finished_at)}`
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            className="field w-64 font-mono text-xs"
            value={inputDir}
            onChange={(e) => setInputDir(e.target.value)}
            aria-label="Input directory"
          />
          <button
            className="btn-primary"
            onClick={() => start.mutate()}
            disabled={start.isPending || run.status === "RUNNING"}
          >
            {run.status === "RUNNING"
              ? "Run in progress"
              : start.isPending
                ? "Starting…"
                : "Start run"}
          </button>
        </div>
      </div>

      {run.status === "RUNNING" ? (
        <button
          onClick={() => navigate(`/runs/${run.id}`)}
          className="panel flex w-full items-center gap-3 px-3.5 py-2.5 text-left hover:bg-surface-sunk"
        >
          <span className="h-2 w-2 animate-pulse rounded-full bg-ink" />
          <span className="text-sm">
            Processing {run.images_processed.toLocaleString()} of{" "}
            {run.images_total.toLocaleString()} images
          </span>
          <span className="ml-auto text-xs text-ink-3">Watch progress →</span>
        </button>
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Products" value={s.products} sub={`${s.versions} artwork versions`} />
        <Stat label="Images checked" value={run.images_total.toLocaleString()} sub={`${run.images_cached.toLocaleString()} unchanged since last run`} />
        <Stat
          label="Stale artwork"
          value={v.STALE_VERSION ?? 0}
          tone={v.STALE_VERSION ? "material" : "neutral"}
          sub={percent(v.STALE_VERSION ?? 0, total, 1) + " of listings"}
        />
        <Stat label="Current" value={v.PASS ?? 0} tone="clear" sub="serving approved artwork" />
        <Stat
          label="Not identified"
          value={v.UNKNOWN_IMAGE ?? 0}
          tone={v.UNKNOWN_IMAGE ? "uncertain" : "neutral"}
          sub="no version explains the image"
        />
        <Stat
          label="Awaiting review"
          value={s.awaiting_review}
          tone={s.awaiting_review ? "material" : "neutral"}
          sub="unacknowledged findings"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="panel">
          <SectionTitle right={<span className="text-2xs text-ink-3">last 6 runs</span>}>
            Stale artwork over time
          </SectionTitle>
          <div className="p-3">
            {s.trend.length < 2 ? (
              <EmptyState
                title="Not enough history yet"
                detail="Trends appear once a second run has completed."
              />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={s.trend} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 3" stroke="#e5e9ee" vertical={false} />
                  <XAxis
                    dataKey="run_id"
                    tickFormatter={(id) => `#${id}`}
                    tick={{ fontSize: 11, fill: "#697585" }}
                    axisLine={{ stroke: "#dde2e8" }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#697585" }}
                    axisLine={false}
                    tickLine={false}
                    allowDecimals={false}
                  />
                  <Tooltip
                    contentStyle={{
                      border: "1px solid #dde2e8",
                      borderRadius: 3,
                      fontSize: 12,
                    }}
                    labelFormatter={(id) => `Run ${id}`}
                  />
                  <Bar dataKey="stale" name="Stale" fill="#c0392f" radius={[2, 2, 0, 0]}
                       isAnimationActive={false} maxBarSize={64} />
                  <Bar dataKey="material" name="Material" fill="#e4a29b" radius={[2, 2, 0, 0]}
                       isAnimationActive={false} maxBarSize={64} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="panel">
          <SectionTitle>Severity of stale listings</SectionTitle>
          <div className="divide-y divide-line">
            {(["MATERIAL", "COSMETIC", "UNCERTAIN", "NONE"] as const).map((k) => {
              const n = s.severities[k] ?? 0;
              const tone = {
                MATERIAL: "text-material",
                COSMETIC: "text-cosmetic",
                UNCERTAIN: "text-uncertain",
                NONE: "text-ink-3",
              }[k];
              return (
                <div key={k} className="flex items-center gap-3 px-3.5 py-2">
                  <span className="text-sm capitalize">{k.toLowerCase()}</span>
                  <span className={`ml-auto font-mono tabular text-sm ${tone}`}>{n}</span>
                  <span className="w-12 text-right font-mono text-2xs text-ink-4">
                    {percent(n, total, 0)}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="border-t border-line px-3.5 py-2.5">
            <button className="btn-ghost w-full justify-center" onClick={() => navigate("/queue")}>
              Open review queue
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
