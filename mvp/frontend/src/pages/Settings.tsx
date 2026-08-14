import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorState, Mono, SectionTitle, Skeleton } from "../components/primitives";
import { metricLabel } from "../lib/meaning";

/**
 * Thresholds beside the measurement they came from.
 *
 * A threshold shown as a bare number invites someone to nudge it, and nothing on
 * the screen tells them what they are trading away. The chart is not decoration:
 * it is the argument for the value, and it belongs next to the input.
 */
export function Settings() {
  const queryClient = useQueryClient();
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });
  const calibration = useQuery({ queryKey: ["calibration"], queryFn: api.calibration });

  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => {
    if (config.data) setDraft({});
  }, [config.data]);

  const save = useMutation({
    mutationFn: (values: Record<string, number>) => api.updateConfig(values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["calibration"] });
    },
  });

  if (config.isLoading) return <Skeleton rows={8} />;
  if (config.isError)
    return <ErrorState error={config.error} retry={() => config.refetch()} />;
  if (!config.data) return null;

  const { values, editable, calibrated } = config.data;
  const dirty = Object.keys(draft).length > 0;

  const submit = () => {
    const parsed: Record<string, number> = {};
    for (const [k, v] of Object.entries(draft)) {
      const n = Number(v);
      if (Number.isFinite(n) && n > 0) parsed[k] = n;
    }
    if (Object.keys(parsed).length) save.mutate(parsed);
  };

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
      <section className="rounded border border-line bg-surface">
        <SectionTitle
          right={
            <span
              className={`rounded border px-1.5 py-0.5 text-2xs ${
                calibrated
                  ? "border-clear-line bg-clear-bg text-clear"
                  : "border-cosmetic-line bg-cosmetic-bg text-cosmetic"
              }`}
            >
              {calibrated ? "measured" : "hand-tuned"}
            </span>
          }
        >
          Thresholds
        </SectionTitle>

        <p className="border-b border-line px-3.5 py-2.5 text-xs text-ink-3">
          {calibrated
            ? "These were measured from known-unchanged pairs, not chosen. Editing one replaces a measurement with a judgement, and this panel will say so."
            : "At least one value has been edited by hand. Re-run the calibration to go back to measured values."}
        </p>

        <dl className="divide-y divide-line">
          {Object.entries(values).map(([key, value]) => {
            const canEdit = editable.includes(key);
            return (
              <div key={key} className="flex items-center gap-3 px-3.5 py-2">
                <dt className="min-w-0 flex-1">
                  <span className="block truncate text-xs text-ink-2">
                    {metricLabel[key] ?? key}
                  </span>
                  <Mono className="text-ink-4">{key}</Mono>
                </dt>
                <dd>
                  {canEdit ? (
                    <input
                      className="field w-28 text-right font-mono tabular"
                      value={draft[key] ?? String(value)}
                      onChange={(e) =>
                        setDraft((d) => ({ ...d, [key]: e.target.value }))
                      }
                      aria-label={key}
                      inputMode="decimal"
                    />
                  ) : (
                    <Mono className="text-ink-3">{String(value)}</Mono>
                  )}
                </dd>
              </div>
            );
          })}
        </dl>

        <div className="flex items-center gap-2 border-t border-line px-3.5 py-2.5">
          <button className="btn-primary btn-sm" disabled={!dirty || save.isPending} onClick={submit}>
            {save.isPending ? "Saving…" : "Save"}
          </button>
          <button className="btn-ghost btn-sm" disabled={!dirty} onClick={() => setDraft({})}>
            Discard
          </button>
          <span className="ml-auto text-2xs text-ink-4">
            Comparisons already run keep the values they used.
          </span>
        </div>

        {save.isError ? (
          <div className="px-3.5 pb-3">
            <ErrorState error={save.error} />
          </div>
        ) : null}
      </section>

      <section className="rounded border border-line bg-surface">
        <SectionTitle>Where the numbers come from</SectionTitle>
        <div className="px-3.5 py-3.5">
          {calibration.data?.chart_url ? (
            <figure>
              <img
                src={calibration.data.chart_url}
                alt="Measured noise floor: distributions of structural and colour difference for unchanged pairs and inside known edits"
                className="w-full rounded border border-line"
              />
              <figcaption className="mt-2 max-w-2xl text-xs text-ink-3">
                Grey is how far an image moves when <em>nothing</em> changed and it was
                merely re-saved, resized or photographed. Red is how far it moves inside
                a known edit. The threshold goes where the two separate.
              </figcaption>
            </figure>
          ) : (
            <p className="text-sm text-ink-3">
              No calibration chart yet. Run{" "}
              <code className="font-mono text-xs">
                python -m tools.calibrate --pairs ../data/pairs
              </code>{" "}
              from the backend directory.
            </p>
          )}

          <CalibrationRecord record={calibration.data?.record} />

          <div className="mt-5 border-t border-line pt-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-2">
              Reader
            </h3>
            <p className="mt-1 text-sm text-ink-2">
              Text is being read by{" "}
              <span className="font-mono">{config.data.ocr_active}</span>.
              {config.data.ocr_active === "none"
                ? " No OCR engine is installed, so every difference will be reported as needing review rather than settled. Install one with: pip install rapidocr-onnxruntime"
                : ""}
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}

function CalibrationRecord({ record }: { record: Record<string, any> | null | undefined }) {
  if (!record) return null;
  const chosen = record.chosen ?? {};
  const separation = record.separation ?? {};
  return (
    <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-3">
      <Item label="Pairs measured" value={record.pairs_used} />
      <Item label="Unchanged pixels" value={fmtInt(record.unchanged_pixels)} />
      <Item label="Pixels inside edits" value={fmtInt(record.changed_pixels)} />
      <Item label="Structure threshold" value={chosen.ssim_threshold} />
      <Item label="Colour threshold" value={chosen.chroma_threshold} />
      <Item label="Percentile used" value={chosen.percentile_used} />
      <Item
        label="Structure separation"
        value={separation.ssim_margin}
        hint="Changed p99 minus unchanged p99.9. Positive means the two populations separate."
      />
      <Item label="Colour separation" value={separation.chroma_margin} />
    </dl>
  );
}

function Item({
  label,
  value,
  hint,
}: {
  label: string;
  value: unknown;
  hint?: string;
}) {
  if (value === undefined || value === null) return null;
  return (
    <div title={hint}>
      <dt className="text-2xs uppercase tracking-wide text-ink-4">{label}</dt>
      <dd className="font-mono tabular text-ink-2">{String(value)}</dd>
    </div>
  );
}

function fmtInt(n: unknown): string {
  return typeof n === "number" ? n.toLocaleString() : String(n ?? "—");
}
