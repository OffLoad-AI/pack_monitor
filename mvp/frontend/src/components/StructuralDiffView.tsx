import { useState } from "react";
import type { Region, Stage } from "../api/types";
import { fileUrl } from "../api/client";

/**
 * The structural-diff stage's own view: an SSIM heatmap over the marketplace
 * image with an opacity slider, and a toggle between the raw mask, the mask
 * after morphology, and the regions that survived.
 *
 * The three masks matter separately. Raw shows what the threshold caught,
 * morphology shows what survived speckle removal and word merging, and the boxes
 * show what was actually read. Seeing only the last of the three makes the
 * filtering look like magic.
 */

type Layer = "heatmap" | "mask_raw" | "mask_morphology" | "regions";

const LAYERS: { id: Layer; label: string; artifact: string; help: string }[] = [
  {
    id: "heatmap",
    label: "Difference map",
    artifact: "ssim_heatmap",
    help: "Brighter means more structurally different. Grey is outside the shared area.",
  },
  {
    id: "mask_raw",
    label: "Over threshold",
    artifact: "mask_raw",
    help: "Every pixel that differs by more than the measured noise floor.",
  },
  {
    id: "mask_morphology",
    label: "After cleaning",
    artifact: "mask_morphology",
    help: "Speckle removed, then characters merged along the line into word-level blobs.",
  },
  {
    id: "regions",
    label: "Regions read",
    artifact: "regions",
    help: "What survived the size filter and was handed to the reading step.",
  },
];

export function StructuralDiffView({
  stage,
  regions,
  frame,
}: {
  stage: Stage;
  regions: Region[];
  frame?: { w: number; h: number };
}) {
  const [layer, setLayer] = useState<Layer>("heatmap");
  const [opacity, setOpacity] = useState(0.7);

  const active = LAYERS.find((l) => l.id === layer)!;
  const overlay = stage.artifacts[active.artifact];
  const base = stage.artifacts.regions;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div
          role="group"
          aria-label="Layer"
          className="inline-flex overflow-hidden rounded border border-line"
        >
          {LAYERS.filter((l) => stage.artifacts[l.artifact]).map((l) => (
            <button
              key={l.id}
              type="button"
              onClick={() => setLayer(l.id)}
              aria-pressed={layer === l.id}
              className={`px-2.5 py-1 text-xs ${
                layer === l.id
                  ? "bg-ink text-white"
                  : "bg-surface text-ink-2 hover:bg-surface-sunk"
              }`}
            >
              {l.label}
            </button>
          ))}
        </div>

        <label className="flex items-center gap-2 text-xs text-ink-3">
          Opacity
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={opacity}
            onChange={(e) => setOpacity(Number(e.target.value))}
            className="w-32"
            aria-label="Overlay opacity"
          />
          <span className="font-mono tabular w-8 text-right">
            {Math.round(opacity * 100)}%
          </span>
        </label>
      </div>

      {overlay ? (
        <figure>
          <div className="relative overflow-hidden rounded border border-line bg-[#f8f9fb]">
            {base ? (
              <img
                src={fileUrl(base)}
                alt=""
                aria-hidden
                className="block w-full"
              />
            ) : null}
            <img
              src={fileUrl(overlay)}
              alt={active.label}
              className="absolute inset-0 block h-full w-full"
              style={{ opacity }}
            />
          </div>
          <figcaption className="mt-1.5 max-w-3xl text-xs text-ink-3">
            {active.help}
          </figcaption>
        </figure>
      ) : null}

      {regions.length ? (
        <p className="text-xs text-ink-3">
          {regions.length} region{regions.length === 1 ? "" : "s"} proposed
          {frame ? ` in a ${frame.w}x${frame.h} frame` : ""}. This step is
          deliberately generous — the reading step decides what is real.
        </p>
      ) : null}
    </div>
  );
}
