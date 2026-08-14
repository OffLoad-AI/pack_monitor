import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import type { Region } from "../api/types";
import { severityStroke } from "../lib/meaning";

/**
 * Zoom and pan, with state shared across panes.
 *
 * The shared state is the point. Two images side by side that scroll
 * independently make you do the work of keeping your place in both; sharing the
 * transform means you are always looking at the same part of the pack in each.
 *
 * Region boxes are held in **fractional** coordinates, so they stay correct
 * under any zoom, pan or display size — the same discipline as the other build's
 * ImageCompare, and the reason clicking a region can highlight the matching box
 * in every view that draws boxes.
 */

interface ViewState {
  scale: number;
  x: number;
  y: number;
}

interface ViewportApi {
  view: ViewState;
  setView: (v: ViewState | ((prev: ViewState) => ViewState)) => void;
  reset: () => void;
  focused: number | null;
  setFocused: (id: number | null) => void;
}

const IDENTITY: ViewState = { scale: 1, x: 0, y: 0 };
const ViewportContext = createContext<ViewportApi | null>(null);

export function ViewportProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState<ViewState>(IDENTITY);
  const [focused, setFocused] = useState<number | null>(null);
  const reset = useCallback(() => setView(IDENTITY), []);
  const value = useMemo(
    () => ({ view, setView, reset, focused, setFocused }),
    [view, focused, reset],
  );
  return (
    <ViewportContext.Provider value={value}>{children}</ViewportContext.Provider>
  );
}

export function useViewport(): ViewportApi {
  const ctx = useContext(ViewportContext);
  if (!ctx) throw new Error("useViewport must be used inside a ViewportProvider");
  return ctx;
}

export interface ImageViewerProps {
  src?: string;
  alt: string;
  caption?: ReactNode;
  /** Boxes in source-image pixels, plus the source dimensions to normalize by. */
  regions?: Region[];
  frameWidth?: number;
  frameHeight?: number;
  overlaySrc?: string;
  overlayOpacity?: number;
  className?: string;
  height?: number;
}

export function ImageViewer({
  src,
  alt,
  caption,
  regions,
  frameWidth,
  frameHeight,
  overlaySrc,
  overlayOpacity = 0,
  className = "",
  height = 380,
}: ImageViewerProps) {
  const { view, setView, reset, focused, setFocused } = useViewport();
  const ref = useRef<HTMLDivElement>(null);
  const dragging = useRef<{ x: number; y: number } | null>(null);

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      if (!ref.current) return;
      e.preventDefault();
      const rect = ref.current.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      setView((v) => {
        const next = Math.min(12, Math.max(1, v.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
        const k = next / v.scale;
        return { scale: next, x: cx - k * (cx - v.x), y: cy - k * (cy - v.y) };
      });
    },
    [setView],
  );

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    // React's onWheel is passive, so preventDefault there is a no-op and the
    // page scrolls behind the zoom. This listener is explicitly non-passive.
    const handler = (e: WheelEvent) => e.preventDefault();
    node.addEventListener("wheel", handler, { passive: false });
    return () => node.removeEventListener("wheel", handler);
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    dragging.current = { x: e.clientX - view.x, y: e.clientY - view.y };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    setView((v) => ({
      ...v,
      x: e.clientX - dragging.current!.x,
      y: e.clientY - dragging.current!.y,
    }));
  };
  const onPointerUp = (e: React.PointerEvent) => {
    dragging.current = null;
    (e.target as Element).releasePointerCapture?.(e.pointerId);
  };

  const boxes =
    regions && frameWidth && frameHeight
      ? regions.map((r) => ({
          region: r,
          left: (r.x / frameWidth) * 100,
          top: (r.y / frameHeight) * 100,
          width: (r.w / frameWidth) * 100,
          height: (r.h / frameHeight) * 100,
        }))
      : [];

  return (
    <figure className={`min-w-0 ${className}`}>
      <div
        ref={ref}
        className="relative overflow-hidden rounded border border-line bg-[#f8f9fb]"
        style={{ height, cursor: dragging.current ? "grabbing" : "grab" }}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        onDoubleClick={reset}
        role="img"
        aria-label={alt}
      >
        {src ? (
          <div
            className="absolute left-0 top-0 origin-top-left"
            style={{
              transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
            }}
          >
            <div className="relative">
              <img
                src={src}
                alt={alt}
                draggable={false}
                className="block max-h-none w-full select-none"
                style={{ maxWidth: "none", width: ref.current?.clientWidth ?? "100%" }}
              />
              {overlaySrc && overlayOpacity > 0 ? (
                <img
                  src={overlaySrc}
                  alt=""
                  draggable={false}
                  aria-hidden
                  className="pointer-events-none absolute inset-0 block h-full w-full select-none"
                  style={{ opacity: overlayOpacity }}
                />
              ) : null}
              {boxes.map(({ region, left, top, width, height: h }) => {
                const active = focused === region.id;
                return (
                  <button
                    key={region.id}
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setFocused(active ? null : region.id);
                    }}
                    aria-label={`Region ${region.ordinal}`}
                    aria-pressed={active}
                    className="absolute"
                    style={{
                      left: `${left}%`,
                      top: `${top}%`,
                      width: `${width}%`,
                      height: `${h}%`,
                      border: `${active ? 3 : 2}px solid ${severityStroke[region.severity]}`,
                      background: active
                        ? `${severityStroke[region.severity]}22`
                        : "transparent",
                      boxShadow: active ? `0 0 0 2px #ffffffcc` : undefined,
                    }}
                  />
                );
              })}
            </div>
          </div>
        ) : (
          <div className="flex h-full items-center justify-center px-6 text-center text-xs text-ink-3">
            This image isn't available. Comparisons run from the command line keep
            their source images outside the server's files directory.
          </div>
        )}

        {view.scale !== 1 || view.x !== 0 || view.y !== 0 ? (
          <button
            className="btn-ghost btn-sm absolute right-2 top-2 bg-surface/90"
            onClick={reset}
          >
            Reset view
          </button>
        ) : null}
      </div>
      {caption ? (
        <figcaption className="mt-1.5 flex items-center justify-between gap-2 text-2xs text-ink-3">
          {caption}
        </figcaption>
      ) : null}
    </figure>
  );
}
