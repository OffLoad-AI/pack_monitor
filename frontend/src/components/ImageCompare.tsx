import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { Region } from "../api/types";

export type CompareMode = "side" | "swipe" | "overlay";

interface Transform {
  scale: number;
  tx: number;
  ty: number;
}

const IDENTITY: Transform = { scale: 1, tx: 0, ty: 0 };
const MIN_SCALE = 1;
const MAX_SCALE = 16;

/** A box in fractional (0..1) image coordinates, so it scales with the image. */
interface FracBox {
  key: string;
  x: number;
  y: number;
  w: number;
  h: number;
  severity: Region["severity"];
  acknowledged: boolean;
}

function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v));
}

/**
 * Keeps the image inside the frame: at scale 1 it is centred, and beyond that it
 * may not be dragged so far that the frame shows empty space.
 */
function constrain(t: Transform, frame: { w: number; h: number }): Transform {
  const scale = clamp(t.scale, MIN_SCALE, MAX_SCALE);
  const maxX = 0;
  const minX = frame.w - frame.w * scale;
  const maxY = 0;
  const minY = frame.h - frame.h * scale;
  return {
    scale,
    tx: clamp(t.tx, minX, maxX),
    ty: clamp(t.ty, minY, maxY),
  };
}

const boxTone: Record<Region["severity"], string> = {
  MATERIAL: "border-material",
  COSMETIC: "border-cosmetic",
  UNCERTAIN: "border-uncertain",
  NONE: "border-ink-4",
};

function RegionBoxes({
  boxes,
  activeKey,
  onPick,
}: {
  boxes: FracBox[];
  activeKey: string | null;
  onPick?: (key: string) => void;
}) {
  return (
    <>
      {boxes.map((b) => {
        const active = b.key === activeKey;
        return (
          <button
            key={b.key}
            type="button"
            aria-label="Zoom to changed region"
            onClick={(e) => {
              e.stopPropagation();
              onPick?.(b.key);
            }}
            className={`absolute border-2 ${boxTone[b.severity]} ${
              active ? "ring-2 ring-focus ring-offset-0" : ""
            } ${b.acknowledged ? "border-dashed opacity-60" : ""}`}
            style={{
              left: `${b.x * 100}%`,
              top: `${b.y * 100}%`,
              width: `${b.w * 100}%`,
              height: `${b.h * 100}%`,
              background: active ? "rgba(37,99,235,0.10)" : "transparent",
              cursor: onPick ? "zoom-in" : "default",
            }}
          />
        );
      })}
    </>
  );
}

function Pane({
  src,
  label,
  boxes,
  transform,
  activeKey,
  onPick,
  onNatural,
}: {
  src: string | null;
  label: string;
  boxes: FracBox[];
  transform: Transform;
  activeKey: string | null;
  onPick?: (key: string) => void;
  onNatural?: (w: number, h: number) => void;
}) {
  return (
    <div className="relative h-full w-full overflow-hidden bg-[#0f1216]">
      <div
        className="absolute inset-0"
        style={{
          transform: `translate(${transform.tx}px, ${transform.ty}px) scale(${transform.scale})`,
          transformOrigin: "0 0",
        }}
      >
        <div className="relative h-full w-full">
          {src ? (
            <img
              src={src}
              alt={label}
              draggable={false}
              onLoad={(e) =>
                onNatural?.(
                  e.currentTarget.naturalWidth,
                  e.currentTarget.naturalHeight,
                )
              }
              className="absolute inset-0 h-full w-full object-contain"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-xs text-ink-4">
              No image
            </div>
          )}
          {/* Boxes sit in the same fractional space as the object-contain image
              only when the frame matches the image aspect. Artwork here is
              square and the frames are square, so they align exactly. */}
          <RegionBoxes boxes={boxes} activeKey={activeKey} onPick={onPick} />
        </div>
      </div>
      <div className="pointer-events-none absolute left-0 top-0 bg-black/65 px-2 py-1 font-mono text-2xs uppercase tracking-wide text-white/90">
        {label}
      </div>
    </div>
  );
}

export function ImageCompare({
  scrapedUrl,
  matchedUrl,
  currentUrl,
  overlayUrl,
  regions,
  matchedLabel,
  currentLabel,
}: {
  scrapedUrl: string | null;
  matchedUrl: string | null;
  currentUrl: string | null;
  overlayUrl: string | null;
  regions: Region[];
  matchedLabel: string;
  currentLabel: string;
}) {
  const [mode, setMode] = useState<CompareMode>("side");
  const [transform, setTransform] = useState<Transform>(IDENTITY);
  const [divider, setDivider] = useState(0.5);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [scrapedNatural, setScrapedNatural] = useState<[number, number]>([1500, 1500]);
  const [refNatural, setRefNatural] = useState<[number, number]>([1500, 1500]);

  const frameRef = useRef<HTMLDivElement>(null);
  const [frame, setFrame] = useState({ w: 1, h: 1 });
  const drag = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);
  const dividerDrag = useRef(false);

  useLayoutEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      // In side-by-side each pane is half the width, so the pan frame is a pane.
      setFrame({ w: mode === "side" ? r.width / 2 : r.width, h: r.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [mode]);

  // Boxes on the reference panes come from artwork coordinates; boxes on the
  // scraped pane come from its own, because the listing image was padded and
  // resized by the marketplace and the two no longer share a coordinate space.
  const refBoxes = useMemo<FracBox[]>(
    () =>
      regions.map((r, i) => ({
        key: r.region_signature ?? `r${i}`,
        x: r.x / refNatural[0],
        y: r.y / refNatural[1],
        w: r.w / refNatural[0],
        h: r.h / refNatural[1],
        severity: r.severity,
        acknowledged: r.acknowledged,
      })),
    [regions, refNatural],
  );

  const scrapedBoxes = useMemo<FracBox[]>(
    () =>
      regions.map((r, i) => {
        const b = r.scraped_box ?? [r.x, r.y, r.w, r.h];
        return {
          key: r.region_signature ?? `r${i}`,
          x: b[0] / scrapedNatural[0],
          y: b[1] / scrapedNatural[1],
          w: b[2] / scrapedNatural[0],
          h: b[3] / scrapedNatural[1],
          severity: r.severity,
          acknowledged: r.acknowledged,
        };
      }),
    [regions, scrapedNatural],
  );

  const zoomToBox = useCallback(
    (key: string) => {
      const b = refBoxes.find((x) => x.key === key) ?? scrapedBoxes.find((x) => x.key === key);
      if (!b || !frame.w) return;
      const pad = 2.2; // show the region with context around it
      const scale = clamp(
        Math.min(1 / (b.w * pad), 1 / (b.h * pad)),
        MIN_SCALE,
        MAX_SCALE,
      );
      const cx = (b.x + b.w / 2) * frame.w;
      const cy = (b.y + b.h / 2) * frame.h;
      setActiveKey(key);
      setTransform(
        constrain(
          { scale, tx: frame.w / 2 - cx * scale, ty: frame.h / 2 - cy * scale },
          frame,
        ),
      );
    },
    [refBoxes, scrapedBoxes, frame],
  );

  // Expose region focus to the surrounding page (the region list drives it too).
  useEffect(() => {
    const handler = (e: Event) => {
      const key = (e as CustomEvent<string>).detail;
      if (key) zoomToBox(key);
    };
    window.addEventListener("pcm:focus-region", handler);
    return () => window.removeEventListener("pcm:focus-region", handler);
  }, [zoomToBox]);

  const onWheel = (e: React.WheelEvent) => {
    if (!frame.w) return;
    e.preventDefault();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const px = e.clientX - rect.left - (mode === "side" && e.clientX - rect.left > frame.w ? frame.w : 0);
    const py = e.clientY - rect.top;
    const factor = Math.exp(-e.deltaY * 0.0016);
    setTransform((t) => {
      const scale = clamp(t.scale * factor, MIN_SCALE, MAX_SCALE);
      const k = scale / t.scale;
      return constrain(
        { scale, tx: px - (px - t.tx) * k, ty: py - (py - t.ty) * k },
        frame,
      );
    });
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (dividerDrag.current) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, tx: transform.tx, ty: transform.ty };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (dividerDrag.current) {
      const rect = frameRef.current!.getBoundingClientRect();
      setDivider(clamp((e.clientX - rect.left) / rect.width, 0.02, 0.98));
      return;
    }
    if (!drag.current) return;
    const d = drag.current;
    setTransform((t) =>
      constrain({ ...t, tx: d.tx + (e.clientX - d.x), ty: d.ty + (e.clientY - d.y) }, frame),
    );
  };

  const endDrag = () => {
    drag.current = null;
    dividerDrag.current = false;
  };

  const reset = () => {
    setTransform(IDENTITY);
    setActiveKey(null);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)
        return;
      if (e.key === "1") setMode("side");
      else if (e.key === "2") setMode("swipe");
      else if (e.key === "3") setMode("overlay");
      else if (e.key === "0") reset();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const modes: { id: CompareMode; label: string; key: string }[] = [
    { id: "side", label: "Side by side", key: "1" },
    { id: "swipe", label: "Swipe", key: "2" },
    { id: "overlay", label: "Difference", key: "3" },
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <div className="flex rounded border border-line">
          {modes.map((m, i) => (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              aria-pressed={mode === m.id}
              className={`px-2.5 py-1 text-xs font-medium ${
                i > 0 ? "border-l border-line" : ""
              } ${
                mode === m.id
                  ? "bg-ink text-white"
                  : "bg-surface text-ink-2 hover:bg-surface-sunk"
              }`}
            >
              {m.label}
              <span className="ml-1.5 font-mono text-2xs opacity-60">{m.key}</span>
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <span className="font-mono tabular text-2xs text-ink-3">
            {transform.scale.toFixed(1)}×
          </span>
          <button className="btn-ghost btn-sm" onClick={reset}>
            Reset view <span className="kbd ml-1">0</span>
          </button>
        </div>
      </div>

      <div
        ref={frameRef}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        className="relative min-h-[22rem] flex-1 touch-none select-none bg-[#0f1216]"
        style={{ cursor: drag.current ? "grabbing" : "grab" }}
      >
        {mode === "side" ? (
          <div className="grid h-full grid-cols-2 gap-px bg-line">
            <Pane
              src={scrapedUrl}
              label="On the listing"
              boxes={scrapedBoxes}
              transform={transform}
              activeKey={activeKey}
              onPick={zoomToBox}
              onNatural={(w, h) => setScrapedNatural([w, h])}
            />
            <Pane
              src={currentUrl}
              label={`Approved · ${currentLabel}`}
              boxes={refBoxes}
              transform={transform}
              activeKey={activeKey}
              onPick={zoomToBox}
              onNatural={(w, h) => setRefNatural([w, h])}
            />
          </div>
        ) : mode === "swipe" ? (
          <div className="relative h-full w-full">
            <Pane
              src={currentUrl}
              label={`Approved · ${currentLabel}`}
              boxes={refBoxes}
              transform={transform}
              activeKey={activeKey}
              onPick={zoomToBox}
              onNatural={(w, h) => setRefNatural([w, h])}
            />
            <div
              className="absolute inset-0"
              style={{ clipPath: `inset(0 ${(1 - divider) * 100}% 0 0)` }}
            >
              {/* Swipe compares the two artwork files, not the listing photo
                  against artwork: both sides are then clean renders at the same
                  scale, so what moves under the divider is the actual edit rather
                  than the marketplace's re-encoding. */}
              <Pane
                src={matchedUrl ?? scrapedUrl}
                label={`Serving · ${matchedLabel}`}
                boxes={refBoxes}
                transform={transform}
                activeKey={activeKey}
                onPick={zoomToBox}
                onNatural={(w, h) => setRefNatural([w, h])}
              />
            </div>
            <div
              role="separator"
              aria-label="Comparison divider"
              aria-valuenow={Math.round(divider * 100)}
              tabIndex={0}
              onPointerDown={(e) => {
                e.stopPropagation();
                dividerDrag.current = true;
                (e.currentTarget.parentElement as HTMLElement).setPointerCapture(
                  e.pointerId,
                );
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft") setDivider((d) => clamp(d - 0.02, 0.02, 0.98));
                if (e.key === "ArrowRight") setDivider((d) => clamp(d + 0.02, 0.02, 0.98));
              }}
              className="absolute top-0 z-20 h-full w-1 -translate-x-1/2 cursor-col-resize bg-white/85"
              style={{ left: `${divider * 100}%` }}
            >
              <div className="absolute left-1/2 top-1/2 h-8 w-8 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-ink/80" />
            </div>
          </div>
        ) : (
          <Pane
            src={overlayUrl ?? scrapedUrl}
            label={overlayUrl ? "Difference overlay" : "On the listing"}
            boxes={overlayUrl ? [] : scrapedBoxes}
            transform={transform}
            activeKey={activeKey}
            onPick={zoomToBox}
            onNatural={(w, h) => setScrapedNatural([w, h])}
          />
        )}
      </div>

      <div className="flex items-center gap-3 border-t border-line px-3 py-1.5 text-2xs text-ink-3">
        <span>Scroll to zoom · drag to pan · click a box to inspect it</span>
        <span className="ml-auto font-mono">
          serving {matchedLabel} · approved {currentLabel}
        </span>
      </div>
    </div>
  );
}
