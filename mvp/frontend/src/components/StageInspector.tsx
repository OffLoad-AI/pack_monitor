import { useEffect, useRef } from "react";
import type { Region, Stage } from "../api/types";
import { fileUrl } from "../api/client";
import {
  HIDDEN_METRICS,
  formatMetric,
  metricLabel,
  stageLabel,
  stagePurpose,
} from "../lib/meaning";
import { ConfidenceBar, Mono, StatusTag } from "./primitives";
import { ImageViewer, useViewport } from "./ImageViewer";
import { RegionReadings } from "./RegionReadings";
import { StructuralDiffView } from "./StructuralDiffView";

/**
 * The vertical sequence of pipeline stages, each expandable to its artefacts,
 * its metrics and its plain-language notes.
 *
 * The three are kept visually distinct on purpose. Notes are prose, written for
 * someone who does not know what a homography is. Metrics are a table of
 * numbers, monospace and comparable. Artefacts are images, given room, because
 * on this screen the images *are* the content.
 */

export interface StageInspectorProps {
  stages: Stage[];
  regions: Region[];
  activeStage: string | null;
  onActivate: (stage: string | null) => void;
  frame?: { w: number; h: number };
}

export function StageInspector({
  stages,
  regions,
  activeStage,
  onActivate,
  frame,
}: StageInspectorProps) {
  return (
    <ol className="divide-y divide-line">
      {stages.map((stage) => (
        <StageRow
          key={`${stage.stage}-${stage.ordinal}`}
          stage={stage}
          regions={regions}
          open={activeStage === stage.stage}
          onToggle={() => onActivate(activeStage === stage.stage ? null : stage.stage)}
          frame={frame}
        />
      ))}
    </ol>
  );
}

function StageRow({
  stage,
  regions,
  open,
  onToggle,
  frame,
}: {
  stage: Stage;
  regions: Region[];
  open: boolean;
  onToggle: () => void;
  frame?: { w: number; h: number };
}) {
  const ref = useRef<HTMLLIElement>(null);

  useEffect(() => {
    if (open) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [open]);

  return (
    <li ref={ref} className="scroll-mt-16">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left hover:bg-surface-sunk"
      >
        <span
          aria-hidden
          className="w-4 shrink-0 text-center font-mono text-2xs text-ink-4"
        >
          {open ? "−" : "+"}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-ink">
            {stageLabel[stage.stage] ?? stage.stage}
          </span>
          <span className="block truncate text-xs text-ink-3">
            {stage.notes[0] ?? stagePurpose[stage.stage] ?? ""}
          </span>
        </span>
        <StatusTag status={stage.status} />
        <ConfidenceBar value={stage.confidence} />
        <Mono className="w-16 shrink-0 text-right text-ink-3">
          {stage.duration_ms < 1
            ? "<1 ms"
            : `${Math.round(stage.duration_ms)} ms`}
        </Mono>
      </button>

      {open ? (
        <div className="border-t border-line bg-surface-sunk/40 px-3.5 py-3.5">
          <p className="mb-3 max-w-3xl text-xs text-ink-3">
            {stagePurpose[stage.stage]}
          </p>

          {stage.notes.length ? (
            <ul className="mb-4 max-w-3xl space-y-1.5">
              {stage.notes.map((note, i) => (
                <li key={i} className="flex gap-2 text-sm text-ink-2">
                  <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-4" />
                  <span>{note}</span>
                </li>
              ))}
            </ul>
          ) : null}

          <StageView stage={stage} regions={regions} frame={frame} />
          <MetricsTable metrics={stage.metrics} />
        </div>
      ) : null}
    </li>
  );
}

/** Each stage gets the view that makes its own evidence legible. */
function StageView({
  stage,
  regions,
  frame,
}: {
  stage: Stage;
  regions: Region[];
  frame?: { w: number; h: number };
}) {
  const art = stage.artifacts;

  switch (stage.stage) {
    case "load_normalize":
      return (
        <Gallery
          items={[
            {
              key: "reference_padding",
              title: "Reference, before",
              caption: "Dimmed areas were stripped as padding.",
            },
            {
              key: "reference_normalized",
              title: "Reference, after",
              caption: "Colour-corrected, flattened, de-padded.",
            },
            {
              key: "marketplace_padding",
              title: "Marketplace, before",
              caption: "Dimmed areas were stripped as padding.",
            },
            {
              key: "marketplace_normalized",
              title: "Marketplace, after",
              caption: "Colour-corrected, flattened, de-padded.",
            },
          ]}
          artifacts={art}
        />
      );

    case "hash":
      return <HashView stage={stage} />;

    case "registration":
      return <RegistrationView stage={stage} />;

    case "structural_diff":
      return <StructuralDiffView stage={stage} regions={regions} frame={frame} />;

    case "region_ocr":
    case "text_compare":
      return <RegionReadings regions={regions} showDiff={stage.stage === "text_compare"} />;

    default:
      return <Gallery items={Object.keys(art).map((k) => ({ key: k, title: k }))} artifacts={art} />;
  }
}

function HashView({ stage }: { stage: Stage }) {
  const ref = String(stage.metrics.reference_sha256 ?? "");
  const mkt = String(stage.metrics.marketplace_sha256 ?? "");
  const equal = Boolean(stage.metrics.equal);
  return (
    <div className="max-w-3xl rounded border border-line bg-surface p-3">
      <dl className="space-y-2">
        <div>
          <dt className="text-2xs uppercase tracking-wide text-ink-3">Reference</dt>
          <dd className="break-all font-mono text-xs text-ink">{ref || "—"}</dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-wide text-ink-3">Marketplace</dt>
          <dd className="break-all font-mono text-xs text-ink">{mkt || "—"}</dd>
        </div>
      </dl>
      <p className={`mt-3 text-sm font-medium ${equal ? "text-clear" : "text-ink-2"}`}>
        {equal ? "Equal — the same file." : "Not equal — a different file."}
      </p>
    </div>
  );
}

function RegistrationView({ stage }: { stage: Stage }) {
  const art = stage.artifacts;
  return (
    <div className="space-y-4">
      {art.checkerboard ? (
        <figure>
          <img
            src={fileUrl(art.checkerboard)}
            alt="Checkerboard blend of the aligned reference and the marketplace image"
            className="w-full rounded border border-line bg-surface"
          />
          <figcaption className="mt-1.5 max-w-3xl text-xs text-ink-3">
            Alternating squares come from each image. If the artwork runs
            continuously across a square edge, the alignment is right; if it steps,
            it is not.
          </figcaption>
        </figure>
      ) : null}
      <Gallery
        items={[
          {
            key: "keypoint_matches",
            title: "Matching landmarks",
            caption: "Only the points the transform actually rests on are drawn.",
          },
          {
            key: "warped_reference",
            title: "Reference, aligned",
            caption: "The reference mapped into the marketplace image's frame.",
          },
          {
            key: "overlap_mask",
            title: "Shared area",
            caption: "White is compared; black is outside one of the two images.",
          },
        ]}
        artifacts={art}
      />
    </div>
  );
}

export function Gallery({
  items,
  artifacts,
}: {
  items: { key: string; title: string; caption?: string }[];
  artifacts: Record<string, string>;
}) {
  const present = items.filter((i) => artifacts[i.key]);
  if (!present.length) return null;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {present.map((item) => (
        <figure key={item.key}>
          <figcaption className="mb-1 text-2xs font-medium uppercase tracking-wide text-ink-3">
            {item.title}
          </figcaption>
          <img
            src={fileUrl(artifacts[item.key])}
            alt={item.title}
            loading="lazy"
            className="w-full rounded border border-line bg-surface"
          />
          {item.caption ? (
            <figcaption className="mt-1 text-xs text-ink-3">{item.caption}</figcaption>
          ) : null}
        </figure>
      ))}
    </div>
  );
}

function MetricsTable({ metrics }: { metrics: Record<string, any> }) {
  const entries = Object.entries(metrics).filter(([k]) => !HIDDEN_METRICS.has(k));
  if (!entries.length) return null;
  return (
    <details className="mt-4 max-w-3xl">
      <summary className="cursor-pointer text-xs font-medium text-ink-2">
        Measurements ({entries.length})
      </summary>
      <table className="dense-table mt-2 border border-line bg-surface">
        <tbody>
          {entries.map(([key, value]) => (
            <tr key={key}>
              <td className="w-1/2 text-ink-2">{metricLabel[key] ?? key}</td>
              <td className="text-right font-mono tabular text-xs">
                {formatMetric(key, value)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

/** Re-exported so the detail page can share one viewport across its panes. */
export { useViewport, ImageViewer };
