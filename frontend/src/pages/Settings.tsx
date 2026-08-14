import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { ErrorState, Mono, SectionTitle, Skeleton } from "../components/primitives";
import { useToast } from "../components/Toast";

/** Only the values a reviewer might reasonably retune, with what each one means. */
const EDITABLE: { key: string; label: string; help: string }[] = [
  {
    key: "luma_threshold",
    label: "Brightness difference",
    help: "How far a pixel's brightness must move before it counts as changed. Measured as the 99.9th percentile of unchanged, re-encoded artwork.",
  },
  {
    key: "chroma_threshold",
    label: "Colour difference",
    help: "The same, for colour. Lower than brightness because compression leaves colour quieter — and a palette shift moves colour far more than brightness.",
  },
  {
    key: "clean_fraction",
    label: "Clean-image cutoff",
    help: "How much of an image may differ before it stops counting as an exact match for a version.",
  },
  {
    key: "region_margin_ratio",
    label: "Evidence margin",
    help: "How much better the best-matching version must be than the runner-up. Raise it to report fewer matches with more certainty; lower it to identify more images and risk a wrong call.",
  },
  {
    key: "region_signal_top_fraction",
    label: "Region focus",
    help: "The share of a region's most-changed pixels used to score it. Small edits are a few percent of their box, so averaging everything buries them.",
  },
  {
    key: "tolerance_radius",
    label: "Alignment tolerance",
    help: "How far, in pixels, a listing image may be misaligned before differences count. Raising it hides real changes — keep it at 1.",
  },
];

export function Settings() {
  const qc = useQueryClient();
  const { notify } = useToast();
  const thresholds = useQuery({ queryKey: ["thresholds"], queryFn: api.thresholds });
  const [draft, setDraft] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!thresholds.data) return;
    const d: Record<string, string> = {};
    EDITABLE.forEach(({ key }) => {
      const v = thresholds.data!.values[key];
      if (typeof v === "number") d[key] = String(v);
    });
    setDraft(d);
  }, [thresholds.data]);

  const save = useMutation({
    mutationFn: () => {
      const values: Record<string, number> = {};
      for (const { key, label } of EDITABLE) {
        const n = Number(draft[key]);
        if (!Number.isFinite(n) || n <= 0) {
          throw new ApiError(`${label} must be a number greater than zero.`, 400);
        }
        values[key] = n;
      }
      return api.updateThresholds(values);
    },
    onSuccess: () => {
      notify("Thresholds saved");
      qc.invalidateQueries({ queryKey: ["thresholds"] });
    },
    onError: (e: ApiError) => notify(e.message, "error"),
  });

  if (thresholds.isLoading) return <div className="p-4"><Skeleton rows={8} /></div>;
  if (thresholds.isError)
    return (
      <div className="p-4">
        <ErrorState error={thresholds.error} retry={() => thresholds.refetch()} />
      </div>
    );

  const t = thresholds.data!;
  const cal = t.calibration;
  const dirty = EDITABLE.some(
    ({ key }) => String(t.values[key] ?? "") !== (draft[key] ?? ""),
  );

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Detection settings</h1>
        <p className="text-xs text-ink-3">
          These values come from measuring the corpus, not from guesswork. The chart
          shows what they were derived from.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[26rem_minmax(0,1fr)]">
        <div className="panel">
          <SectionTitle
            right={
              <span className="text-2xs text-ink-3">
                {t.values.calibrated ? "calibrated" : "edited by hand"}
              </span>
            }
          >
            Thresholds
          </SectionTitle>

          <div className="divide-y divide-line">
            {EDITABLE.map(({ key, label, help }) => (
              <label key={key} className="block px-3.5 py-2.5">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">{label}</span>
                  <input
                    className="field w-24 text-right font-mono tabular text-xs"
                    value={draft[key] ?? ""}
                    onChange={(e) =>
                      setDraft((d) => ({ ...d, [key]: e.target.value }))
                    }
                    inputMode="decimal"
                  />
                </div>
                <p className="mt-1 text-xs text-ink-3">{help}</p>
              </label>
            ))}
          </div>

          <div className="border-t border-line px-3.5 py-3">
            <div className="rounded border border-cosmetic-line bg-cosmetic-bg px-2.5 py-2 text-xs text-cosmetic">
              Changing these affects the next run only. Completed runs keep the
              settings they were run with, so past reports never change.
            </div>
            <div className="mt-2.5 flex gap-2">
              <button
                className="btn-primary"
                onClick={() => save.mutate()}
                disabled={!dirty || save.isPending}
              >
                {save.isPending ? "Saving…" : "Save thresholds"}
              </button>
              <button
                className="btn-ghost"
                disabled={!dirty}
                onClick={() => {
                  const d: Record<string, string> = {};
                  EDITABLE.forEach(({ key }) => (d[key] = String(t.values[key] ?? "")));
                  setDraft(d);
                }}
              >
                Discard changes
              </button>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="panel">
            <SectionTitle>Where these numbers come from</SectionTitle>
            {t.chart_url ? (
              <img
                src={t.chart_url}
                alt="Noise floor: difference distributions for unchanged and changed artwork"
                className="w-full"
              />
            ) : (
              <p className="px-3.5 py-4 text-sm text-ink-3">
                No calibration chart yet. Run{" "}
                <code className="font-mono text-xs">
                  python -m tools.calibrate --corpus ./data/corpus
                </code>
                .
              </p>
            )}
          </div>

          {cal ? (
            <div className="panel">
              <SectionTitle>Measured separation</SectionTitle>
              <dl className="grid grid-cols-2 gap-x-4 px-3.5 py-3 text-sm">
                {[
                  ["Brightness noise ceiling", cal.luma?.unchanged_p99_9],
                  ["Brightness change level", cal.luma?.changed_p99],
                  ["Colour noise ceiling", cal.chroma?.unchanged_p99_9],
                  ["Colour change level", cal.chroma?.changed_p99],
                  ["Pixels sampled", cal.unchanged_pixels?.toLocaleString?.()],
                  ["Corpus", cal.corpus?.split?.("/").slice(-1)[0]],
                ].map(([k, v]) => (
                  <div key={String(k)} className="flex justify-between gap-2 py-0.5">
                    <dt className="text-ink-3">{k}</dt>
                    <dd>
                      <Mono>{v ?? "—"}</Mono>
                    </dd>
                  </div>
                ))}
              </dl>
              {cal.region_overlap_warning ? (
                <p className="border-t border-line px-3.5 py-2.5 text-xs text-cosmetic">
                  Some edits overlap the noise floor at the smallest sizes and lowest
                  qualities. Those listings are reported as not identified rather
                  than guessed at.
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
