"""Region extraction and box geometry.

Turns a change mask into the boxes a reviewer acts on, and provides the box
relations the reference stage needs to map detected regions onto known edits.
"""

from __future__ import annotations

from typing import Any, Sequence

import cv2
import numpy as np

Box = tuple[int, int, int, int]


def extract_regions(mask: np.ndarray, min_area_fraction: float,
                    morph_close: int = 25) -> list[dict]:
    """Connected components of a change mask, as bounding boxes.

    The close merges adjacent glyphs into one blob so a changed number reads as a
    single region rather than one per digit. At 25px it also merges a logo or a
    badge into one box — the unit a reviewer acts on — which halves the region
    count without ever bridging two separate edits.
    """
    m = mask.copy()
    if morph_close and morph_close > 1:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (morph_close, morph_close))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)

    total = m.shape[0] * m.shape[1]
    n, _labels, stats, _cent = cv2.connectedComponentsWithStats(m, connectivity=8)

    regions = []
    for i in range(1, n):
        x, y, w, h, area = (
            int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]),
            int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]),
            int(stats[i, cv2.CC_STAT_AREA]))
        box_fraction = (w * h) / total
        if box_fraction < min_area_fraction:
            continue
        regions.append({
            "x": x, "y": y, "w": w, "h": h,
            "area_fraction": box_fraction,
            "pixel_area": area,
        })
    # Deterministic ordering: top-to-bottom, then left-to-right. Run-to-run
    # stability of this list is what keeps reviewer sign-offs attached.
    regions.sort(key=lambda r: (r["y"], r["x"], r["w"], r["h"]))
    return regions


def collapse_if_global(regions: list[dict], width: int, height: int,
                       min_regions: int = 20,
                       area_fraction: float = 0.25) -> list[dict]:
    """Report a change touching most of the canvas as a single region.

    A hue shift decomposes into one component per coloured element. That is
    technically accurate and useless to review: the reviewer wants one row saying
    the palette moved, not fifty saying each badge did.
    """
    if len(regions) < min_regions:
        return regions

    x0 = min(r["x"] for r in regions)
    y0 = min(r["y"] for r in regions)
    x1 = max(r["x"] + r["w"] for r in regions)
    y1 = max(r["y"] + r["h"] for r in regions)
    union_fraction = ((x1 - x0) * (y1 - y0)) / float(width * height)
    if union_fraction < area_fraction:
        return regions

    return [{
        "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
        "area_fraction": union_fraction,
        "pixel_area": sum(r["pixel_area"] for r in regions),
    }]


def as_box(v: Any) -> Box:
    """Accept a box as a dict, a sequence, or any object with x/y/w/h.

    Boxes arrive from three places — freshly extracted dicts, stored metadata
    lists, and ORM rows — and callers should not have to convert.
    """
    if isinstance(v, dict):
        return v["x"], v["y"], v["w"], v["h"]
    if hasattr(v, "x") and hasattr(v, "w"):
        return v.x, v.y, v.w, v.h
    x, y, w, h = v
    return x, y, w, h


def iou(a: Any, b: Any) -> float:
    ax, ay, aw, ah = as_box(a)
    bx, by, bw, bh = as_box(b)
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def containment(a: Any, b: Any) -> float:
    """Fraction of box `a` lying inside box `b`.

    IoU alone is the wrong relation when one logical edit surfaces as several
    components — a changed nutrient updates both the per-100g and per-serving
    column, hundreds of pixels apart, while the edit is recorded as a single union
    box. Each small component has terrible IoU against that union; containment
    catches them, and IoU still catches the case where the detected box is larger.
    """
    ax, ay, aw, ah = as_box(a)
    bx, by, bw, bh = as_box(b)
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return ((x1 - x0) * (y1 - y0)) / float(aw * ah) if aw * ah else 0.0


def overlap_score(a: Any, b: Any) -> float:
    """The relation used to match a detected region to a known edit."""
    return max(iou(a, b), containment(a, b))


def scale_box(box: Sequence[int] | Box, scale: float,
              bounds: tuple[int, int]) -> Box:
    """Map a box from reference coordinates into working coordinates, clipped."""
    w_max, h_max = bounds
    x = int(round(box[0] * scale))
    y = int(round(box[1] * scale))
    w = max(1, int(round(box[2] * scale)))
    h = max(1, int(round(box[3] * scale)))
    x = max(0, min(x, w_max - 1))
    y = max(0, min(y, h_max - 1))
    w = min(w, w_max - x)
    h = min(h, h_max - y)
    return x, y, w, h
