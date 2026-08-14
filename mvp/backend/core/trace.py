"""The trace layer.

This is not debug instrumentation bolted on afterwards — **it is the product**.
Every stage emits a `StageTrace`, the trace is persisted, and the frontend exists
to display it. A stage that fails must still emit a trace explaining what it saw
and why it stopped; silent failure is the one unacceptable outcome, because the
entire purpose of this build is to show the method working or not working.

Two fields carry the numbers and two carry the words, and they are deliberately
not the same field:

* `metrics` is machine-readable evidence — `{"inliers": 214}` — rendered as a
  table, sortable, comparable across comparisons.
* `notes` is written for a **non-engineer reading the screen**. Not
  `"inliers=214, cond=8.3"` but `"Found 214 matching points between the two
  images. The alignment is well-conditioned."`

Mixing them produces a UI that is either unreadable or uninspectable.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# Stage status. `DEGRADED` is not a warning to be ignored: it means the stage
# produced an answer the next stage should trust less, and the verdict stage
# reads it.
OK = "OK"
DEGRADED = "DEGRADED"
FAILED = "FAILED"
SKIPPED = "SKIPPED"

STATUSES = (OK, DEGRADED, FAILED, SKIPPED)

# Artefacts are review aids displayed at screen sizes, never the source of truth.
# The version-identification build filled a disk with full-resolution lossless
# overlays; capping the long edge and encoding photographic artefacts as JPEG
# costs nothing visible and two orders of magnitude of storage.
ARTIFACT_MAX_EDGE = 1200
ARTIFACT_JPEG_QUALITY = 88


@dataclass
class StageTrace:
    """What one stage saw, what it concluded, and what it can show for it."""

    stage: str
    status: str = OK
    duration_ms: float = 0.0
    confidence: float | None = None          # 0..1, stage-specific meaning
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)   # name -> path under data/
    notes: list[str] = field(default_factory=list)

    def note(self, text: str) -> None:
        self.notes.append(text)

    def metric(self, **values: Any) -> None:
        for k, v in values.items():
            self.metrics[k] = _jsonable(v)

    def to_row(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "confidence": self.confidence,
            "metrics_json": json.dumps(self.metrics, sort_keys=True),
            "artifacts_json": json.dumps(self.artifacts, sort_keys=True),
            "notes_json": json.dumps(self.notes),
        }


def _jsonable(v: Any) -> Any:
    """Numpy scalars are not JSON-serializable and turn up everywhere here."""
    if isinstance(v, (np.floating, float)):
        f = float(v)
        # Infinity and NaN are legitimate measurements (a degenerate homography
        # has an infinite condition number) but they are not JSON.
        if not np.isfinite(f):
            return None
        return round(f, 6)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, np.ndarray):
        return [_jsonable(x) for x in v.reshape(-1).tolist()]
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    return v


class TraceRecorder:
    """Collects stage traces and writes their artefacts to disk.

    Owns artefact naming so no stage has to know the directory layout, and so a
    stage cannot accidentally overwrite another's file.
    """

    def __init__(self, comparison_id: int, root: Path, data_root: Path,
                 on_trace: Any = None) -> None:
        self.comparison_id = comparison_id
        self.root = Path(root)
        self.data_root = Path(data_root)
        self.traces: list[StageTrace] = []
        # Called as each trace completes. This is how the API reports progress
        # while a comparison runs, rather than only when it finishes — a
        # registration stage takes a couple of seconds and the screen should say
        # what it is doing.
        self._on_trace = on_trace

    # -- lifecycle ---------------------------------------------------------

    def begin(self, stage: str) -> tuple[StageTrace, float]:
        return StageTrace(stage=stage), time.perf_counter()

    def finish(self, trace: StageTrace, started: float) -> StageTrace:
        trace.duration_ms = (time.perf_counter() - started) * 1000.0
        self._append(trace)
        return trace

    def skipped(self, stage: str, why: str) -> StageTrace:
        """A stage that did not need to run still gets a row, saying so."""
        t = StageTrace(stage=stage, status=SKIPPED)
        t.note(why)
        self._append(t)
        return t

    def _append(self, trace: StageTrace) -> None:
        self.traces.append(trace)
        if self._on_trace is not None:
            try:
                self._on_trace(trace)
            except Exception:  # noqa: BLE001 — a progress listener must never
                # be able to fail a comparison that has already done the work.
                pass

    # -- artefacts ---------------------------------------------------------

    def write_image(self, trace: StageTrace, name: str, img: np.ndarray,
                    rgb: bool = True, lossless: bool = False) -> str:
        """Write one artefact and register it on the trace under `name`.

        Masks and overlays are written lossless (they are flat-colour and
        compress to almost nothing); photographic artefacts are JPEG, because a
        full-resolution PNG of a pack front is ~400KB and there are nine of them
        per comparison.
        """
        out = self.root / trace.stage
        out.mkdir(parents=True, exist_ok=True)

        arr = _fit(img)
        if arr.ndim == 2:
            data = arr
        else:
            data = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR) if rgb else arr

        ext = "png" if lossless or arr.ndim == 2 else "jpg"
        path = out / f"{name}.{ext}"
        params = ([] if ext == "png"
                  else [int(cv2.IMWRITE_JPEG_QUALITY), ARTIFACT_JPEG_QUALITY])
        ok = cv2.imwrite(str(path), data, params)
        if not ok:  # pragma: no cover - only on a full or unwritable disk
            raise OSError(f"could not write artefact {path}")

        rel = str(path.resolve().relative_to(self.data_root.resolve())).replace("\\", "/")
        trace.artifacts[name] = rel
        return rel


def _fit(img: np.ndarray) -> np.ndarray:
    """Downscale to the artefact cap, preserving aspect. Never upscales."""
    h, w = img.shape[:2]
    long_edge = max(h, w)
    if long_edge <= ARTIFACT_MAX_EDGE:
        return img
    s = ARTIFACT_MAX_EDGE / long_edge
    return cv2.resize(img, (max(1, int(round(w * s))), max(1, int(round(h * s)))),
                      interpolation=cv2.INTER_AREA)
