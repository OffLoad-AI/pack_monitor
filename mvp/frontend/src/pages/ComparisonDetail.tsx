import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fileUrl } from "../api/client";
import type { ComparisonDetail as Detail, Progress, Region } from "../api/types";
import {
  ConfidenceBar,
  ErrorState,
  Mono,
  SectionTitle,
  SeverityTag,
  Skeleton,
  VerdictTag,
} from "../components/primitives";
import {
  ImageViewer,
  ViewportProvider,
  useViewport,
} from "../components/ImageViewer";
import { StageInspector } from "../components/StageInspector";
import { differenceLabel, stageLabel, verdictHint } from "../lib/meaning";

export function ComparisonDetail() {
  const { id } = useParams();
  const comparisonId = Number(id);
  const queryClient = useQueryClient();

  const detail = useQuery({
    queryKey: ["comparison", comparisonId],
    queryFn: () => api.get(comparisonId),
    enabled: Number.isFinite(comparisonId),
  });

  const running =
    detail.data?.status === "QUEUED" || detail.data?.status === "RUNNING";
  const [progress, setProgress] = useState<Progress | null>(null);

  // Stage-by-stage progress while it runs. The stream is the live view; the
  // query is refetched once at the end so the finished page is the persisted
  // record rather than an accumulation of stream events.
  useEffect(() => {
    if (!running || !Number.isFinite(comparisonId)) return;
    const source = new EventSource(`/api/comparisons/${comparisonId}/stream`);
    source.addEventListener("progress", (e) =>
      setProgress(JSON.parse((e as MessageEvent).data)),
    );
    source.addEventListener("done", () => {
      source.close();
      queryClient.invalidateQueries({ queryKey: ["comparison", comparisonId] });
    });
    source.onerror = () => source.close();
    return () => source.close();
  }, [running, comparisonId, queryClient]);

  if (detail.isLoading) return <Skeleton rows={10} />;
  if (detail.isError)
    return <ErrorState error={detail.error} retry={() => detail.refetch()} />;
  if (!detail.data) return null;

  return (
    <ViewportProvider>
      <Body detail={detail.data} progress={progress} />
    </ViewportProvider>
  );
}

function Body({
  detail,
  progress,
}: {
  detail: Detail;
  progress: Progress | null;
}) {
  const { focused, setFocused } = useViewport();
  const [activeStage, setActiveStage] = useState<string | null>(null);

  const stageOrder = detail.stages.map((s) => s.stage);
  const running = detail.status === "QUEUED" || detail.status === "RUNNING";

  const frame = useFrameSize(detail);
  const panes = useNormalizedPanes(detail);

  // The "play" control: advance through the stages one at a time. Someone
  // watching over your shoulder should understand the method without you
  // narrating it, which is the entire point of this build.
  const step = useCallback(
    (delta: number) => {
      setActiveStage((current) => {
        if (!stageOrder.length) return null;
        const i = current ? stageOrder.indexOf(current as (typeof stageOrder)[number]) : -1;
        const next = Math.min(stageOrder.length - 1, Math.max(0, i + delta));
        return stageOrder[next];
      });
    },
    [stageOrder],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el?.tagName === "INPUT" || el?.tagName === "TEXTAREA") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        step(1);
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        step(-1);
      } else if (e.key === "Escape") {
        setActiveStage(null);
        setFocused(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, setFocused]);

  const material = detail.regions.filter((r) => r.severity === "MATERIAL");
  const notable = detail.regions.filter((r) => r.severity !== "NONE");

  return (
    <div className="space-y-5">
      <Link to="/history" className="text-xs text-ink-3 hover:text-ink">
        ← All comparisons
      </Link>

      {/* Verdict, stated plainly, with what it means. */}
      <section className="rounded border border-line bg-surface px-4 py-3.5">
        <div className="flex flex-wrap items-center gap-3">
          <VerdictTag verdict={detail.verdict} size="lg" />
          {detail.label ? (
            <span className="text-sm text-ink-2">{detail.label}</span>
          ) : null}
          <span className="ml-auto flex items-center gap-4 text-2xs text-ink-3">
            <span className="flex items-center gap-1.5">
              confidence <ConfidenceBar value={detail.confidence} />
            </span>
            <Mono>{Math.round(detail.duration_ms)} ms</Mono>
            <Mono>v{detail.pipeline_version}</Mono>
          </span>
        </div>
        <p className="mt-2 max-w-3xl text-sm text-ink-2">
          {detail.verdict ? verdictHint[detail.verdict] : "Not run yet."}
        </p>
        {detail.error ? (
          <p className="mt-2 font-mono text-xs text-material">{detail.error}</p>
        ) : null}
        {running ? (
          <LiveProgress progress={progress} />
        ) : null}
      </section>

      {/* The two images, with shared zoom and pan. */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-2">
            The pair
          </h2>
          <span className="text-2xs text-ink-4">
            Scroll to zoom, drag to pan. Both panes move together. Double-click to reset.
          </span>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <ImageViewer
            src={panes.reference ?? fileUrl(detail.reference_image)}
            alt="Reference artwork"
            caption={<><span>Reference</span><Mono>{shortHash(detail.reference_sha256)}</Mono></>}
          />
          <ImageViewer
            src={panes.marketplace ?? fileUrl(detail.marketplace_image)}
            alt="Marketplace image"
            regions={panes.marketplace ? notable : undefined}
            frameWidth={frame?.w}
            frameHeight={frame?.h}
            caption={<><span>Marketplace</span><Mono>{shortHash(detail.marketplace_sha256)}</Mono></>}
          />
        </div>
        <p className="mt-1.5 text-2xs text-ink-4">
          Shown after padding was stripped and colour standardised — the frame the
          regions are measured in.
        </p>
      </section>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        {/* The inspector. */}
        <section className="min-w-0 rounded border border-line bg-surface">
          <SectionTitle
            right={
              <div className="flex items-center gap-1">
                <button
                  className="btn-ghost btn-sm"
                  onClick={() => step(-1)}
                  disabled={!stageOrder.length}
                  aria-label="Previous step"
                >
                  ‹ Back
                </button>
                <button
                  className="btn-ghost btn-sm"
                  onClick={() => step(1)}
                  disabled={!stageOrder.length}
                  aria-label="Next step"
                >
                  Step ›
                </button>
              </div>
            }
          >
            How it decided
          </SectionTitle>
          {detail.stages.length ? (
            <StageInspector
              stages={detail.stages}
              regions={detail.regions}
              activeStage={activeStage}
              onActivate={setActiveStage}
              frame={frame ? { w: frame.w, h: frame.h } : undefined}
            />
          ) : (
            <p className="px-3.5 py-6 text-sm text-ink-3">
              No steps have been recorded yet.
            </p>
          )}
        </section>

        {/* Region list. Clicking one highlights it in every view that draws boxes. */}
        <aside className="rounded border border-line bg-surface lg:sticky lg:top-16 lg:self-start">
          <SectionTitle right={<span className="text-2xs text-ink-3">{notable.length}</span>}>
            Regions
          </SectionTitle>
          {notable.length ? (
            <ul className="max-h-[32rem] divide-y divide-line overflow-auto">
              {notable.map((region) => (
                <RegionRow
                  key={region.id}
                  region={region}
                  active={focused === region.id}
                  onSelect={() => {
                    setFocused(focused === region.id ? null : region.id);
                    setActiveStage("text_compare");
                  }}
                />
              ))}
            </ul>
          ) : (
            <p className="px-3.5 py-6 text-sm text-ink-3">
              {material.length
                ? ""
                : "Nothing differed beyond what re-encoding explains."}
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}

function RegionRow({
  region,
  active,
  onSelect,
}: {
  region: Region;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={active}
        className={`w-full px-3.5 py-2.5 text-left hover:bg-surface-sunk ${
          active ? "bg-surface-sunk" : ""
        }`}
      >
        <div className="flex items-center gap-2">
          <SeverityTag severity={region.severity} />
          <Mono className="ml-auto text-ink-4">#{region.ordinal}</Mono>
        </div>
        <div className="mt-1 text-xs font-medium text-ink-2">
          {differenceLabel[region.difference_type] ?? region.difference_type}
        </div>
        <p className="mt-0.5 line-clamp-3 text-xs text-ink-3">{region.detail}</p>
      </button>
    </li>
  );
}

function LiveProgress({ progress }: { progress: Progress | null }) {
  const expected = progress?.expected_stages ?? [];
  const done = new Set((progress?.completed ?? []).map((c) => c.stage));
  return (
    <div className="mt-3">
      <ol className="flex flex-wrap gap-1.5">
        {expected.map((stage) => (
          <li
            key={stage}
            className={`rounded border px-2 py-0.5 text-2xs ${
              done.has(stage)
                ? "border-line-strong bg-surface-sunk text-ink-2"
                : "border-dashed border-line text-ink-4"
            }`}
          >
            {stageLabel[stage] ?? stage}
          </li>
        ))}
      </ol>
      <p className="mt-2 text-xs text-ink-3" role="status">
        {progress?.completed?.length
          ? progress.completed[progress.completed.length - 1].notes[0]
          : "Starting…"}
      </p>
    </div>
  );
}

/**
 * Region boxes are stored in marketplace-frame pixels, so drawing them needs
 * that frame's size. It is not in the response as a field — it is exactly the
 * normalized marketplace image's size, which the load stage measured.
 */
function useFrameSize(detail: Detail) {
  return useMemo(() => {
    const load = detail.stages.find((s) => s.stage === "load_normalize");
    const size = load?.metrics?.marketplace_content_size;
    if (Array.isArray(size) && size.length === 2)
      return { w: Number(size[0]), h: Number(size[1]) };
    return undefined;
  }, [detail.stages]);
}

/**
 * The panes show the **normalized** images, not the raw uploads.
 *
 * Region boxes are measured in the de-padded marketplace frame, so drawing them
 * over a padded upload would offset every box by the padding width. Showing the
 * frame the measurements were actually taken in is both correct and more
 * honest — it is what the pipeline saw.
 */
function useNormalizedPanes(detail: Detail) {
  return useMemo(() => {
    const load = detail.stages.find((s) => s.stage === "load_normalize");
    return {
      reference: fileUrl(load?.artifacts?.reference_normalized),
      marketplace: fileUrl(load?.artifacts?.marketplace_normalized),
    };
  }, [detail.stages]);
}

function shortHash(hash: string | null): string {
  return hash ? hash.slice(0, 10) : "—";
}
