"""Diff overlays — the pre-rendered review aid.

Written only for stale findings that actually have changed regions.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import cv2

from core.imaging.loader import load_rgb

# The overlay is a review aid, not a forensic record — the viewer also draws the
# regions as vectors over the full-resolution image. Stored full-size and lossless
# it costs ~400KB per finding, which at 15,000 images a month is several gigabytes
# per run, kept forever. Capped and JPEG-encoded it is ~40KB and visually identical
# at review sizes.
OVERLAY_MAX_EDGE = 1200
OVERLAY_QUALITY = 85

MATERIAL_RGB = (220, 38, 38)
COSMETIC_RGB = (217, 119, 6)
FILL_OPACITY = 0.32


def write_diff_overlay(src_path: str | Path, boxes: list[dict],
                       out_path: Path) -> str:
    """Changed regions as a translucent fill plus a border, on the listing image."""
    img = load_rgb(src_path)
    h, w = img.shape[:2]
    scale = min(1.0, OVERLAY_MAX_EDGE / max(w, h))
    if scale < 1.0:
        img = cv2.resize(
            img, (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            interpolation=cv2.INTER_AREA)

    overlay = img.copy()
    drawn = []
    for b in boxes:
        x, y, bw, bh = (int(round(v * scale)) for v in b["scraped_box"])
        colour = MATERIAL_RGB if b["severity"] == "MATERIAL" else COSMETIC_RGB
        drawn.append((x, y, bw, bh, colour))
        cv2.rectangle(overlay, (x, y), (x + bw, y + bh), colour, thickness=-1)

    blended = cv2.addWeighted(overlay, FILL_OPACITY, img, 1.0 - FILL_OPACITY, 0)
    for x, y, bw, bh, colour in drawn:
        cv2.rectangle(blended, (x, y), (x + bw, y + bh), colour, thickness=2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), cv2.cvtColor(blended, cv2.COLOR_RGB2BGR),
                [int(cv2.IMWRITE_JPEG_QUALITY), OVERLAY_QUALITY])
    return str(out_path)


def prune_diff_dirs(diff_root: Path, keep: int = 6) -> int:
    """Keep overlays for the most recent runs only.

    They are regenerable from the run's inputs and the dashboard only reaches back
    six runs. Unbounded, this directory grew to 2.5GB and filled the disk.
    """
    if not diff_root.exists():
        return 0
    dirs = sorted(
        (d for d in diff_root.iterdir() if d.is_dir() and d.name.isdigit()),
        key=lambda d: int(d.name), reverse=True)
    removed = 0
    for d in dirs[keep:]:
        shutil.rmtree(d, ignore_errors=True)
        removed += 1
    return removed
