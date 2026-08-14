import type { Region } from "../api/types";
import { fileUrl } from "../api/client";
import { differenceLabel } from "../lib/meaning";
import { SeverityTag } from "./primitives";
import { useViewport } from "./ImageViewer";
import { WordDiff } from "./WordDiff";

/**
 * Per region: both crops side by side, magnified, with the reading beneath
 * each — and, on the text-comparison stage, the word-level diff.
 *
 * Showing the crops rather than only the strings is the whole argument. A reader
 * who can see "480" in one crop and "450" in the other does not have to take the
 * tool's word for anything, which is the difference between a report and an
 * instrument.
 */
export function RegionReadings({
  regions,
  showDiff,
}: {
  regions: Region[];
  showDiff: boolean;
}) {
  const { focused, setFocused } = useViewport();

  if (!regions.length)
    return (
      <p className="text-sm text-ink-3">
        No regions were proposed, so there was nothing to read.
      </p>
    );

  return (
    <ul className="space-y-3">
      {regions.map((region) => {
        const active = focused === region.id;
        return (
          <li
            key={region.id}
            id={`region-${region.id}`}
            className={`rounded border bg-surface p-3 ${
              active ? "border-ink-3 ring-1 ring-ink-4" : "border-line"
            }`}
          >
            <div className="mb-2.5 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setFocused(active ? null : region.id)}
                className="font-mono text-2xs text-ink-3 hover:text-ink"
                aria-pressed={active}
              >
                Region {region.ordinal}
              </button>
              <SeverityTag severity={region.severity} />
              <span className="text-2xs text-ink-3">
                {differenceLabel[region.difference_type] ?? region.difference_type}
              </span>
              {!region.ocr_reliable ? (
                <span className="rounded border border-uncertain-line bg-uncertain-bg px-1.5 py-0.5 text-2xs text-uncertain">
                  Reading unstable
                </span>
              ) : null}
              <span className="ml-auto font-mono tabular text-2xs text-ink-4">
                {region.w}x{region.h} px
              </span>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <CropPane
                title="Reference"
                src={fileUrl(region.ref_crop_path)}
                text={region.reference_text}
              />
              <CropPane
                title="Marketplace"
                src={fileUrl(region.mkt_crop_path)}
                text={region.marketplace_text}
              />
            </div>

            {showDiff ? (
              <div className="mt-3 border-t border-line pt-2.5">
                <WordDiff
                  reference={region.reference_text ?? ""}
                  marketplace={region.marketplace_text ?? ""}
                />
                <p className="mt-2 text-sm text-ink-2">{region.detail}</p>
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function CropPane({
  title,
  src,
  text,
}: {
  title: string;
  src?: string;
  text: string | null;
}) {
  return (
    <figure className="min-w-0">
      <figcaption className="mb-1 text-2xs font-medium uppercase tracking-wide text-ink-3">
        {title}
      </figcaption>
      <div className="flex min-h-[3rem] items-center justify-center overflow-auto rounded border border-line bg-[#f8f9fb] p-1.5">
        {src ? (
          <img src={src} alt={`${title} crop`} loading="lazy" className="max-w-full" />
        ) : (
          <span className="text-2xs text-ink-4">no crop</span>
        )}
      </div>
      <figcaption className="mt-1.5 break-words font-mono text-xs text-ink">
        {text ? `“${text}”` : <span className="text-ink-4">no text read</span>}
      </figcaption>
    </figure>
  );
}
