"""Compatibility shim — the implementation now lives in `core.imaging`.

Differencing and region extraction moved to `core.imaging.metrics` and
`core.imaging.regions`, where they take explicit thresholds rather than a config
dict. This module keeps the old names and dict-taking signatures for existing
callers; new code should import from `core.imaging` directly.
"""

from __future__ import annotations

import numpy as np

from core.imaging.metrics import (  # noqa: F401  (re-exported)
    changed_mask,
    diff_channels,
    region_signal,
)
from core.imaging.metrics import changed_fraction as _changed_fraction
from core.imaging.metrics import diff_score as _diff_score
from core.imaging.metrics import region_changed_fraction as _region_changed_fraction
from core.imaging.regions import (  # noqa: F401  (re-exported)
    as_box,
    containment,
    iou,
    overlap_score,
    scale_box,
)
from core.imaging.regions import collapse_if_global as _collapse_if_global
from core.imaging.regions import extract_regions as _extract_regions

__all__ = [
    "as_box", "changed_fraction", "changed_mask", "collapse_if_global",
    "containment", "diff_channels", "diff_score", "extract_regions", "iou",
    "overlap_score", "reference_regions", "region_changed_fraction",
    "region_signal", "scale_box",
]


def diff_score(a_rgb: np.ndarray, b_rgb: np.ndarray, cfg,
               tolerance_radius: int | None = None) -> np.ndarray:
    r = cfg["tolerance_radius"] if tolerance_radius is None else tolerance_radius
    return _diff_score(a_rgb, b_rgb, cfg["luma_threshold"],
                       cfg["chroma_threshold"], r)


def changed_fraction(score: np.ndarray, threshold: float,
                     morph_open: int = 3) -> float:
    return _changed_fraction(score, threshold, morph_open)


def extract_regions(mask: np.ndarray, min_area_fraction: float,
                    morph_close: int = 7) -> list[dict]:
    return _extract_regions(mask, min_area_fraction, morph_close)


def collapse_if_global(regions: list[dict], width: int, height: int,
                       cfg) -> list[dict]:
    return _collapse_if_global(
        regions, width, height,
        cfg.get("global_change_min_regions", 20),
        cfg.get("global_change_area_fraction", 0.25))


def region_changed_fraction(score: np.ndarray, box: tuple[int, int, int, int],
                            threshold: float, morph_open: int = 3) -> float:
    return _region_changed_fraction(score, box, threshold, morph_open)


def reference_regions(ref_a: np.ndarray, ref_b: np.ndarray, cfg) -> list[dict]:
    """Diff two of our own artwork files.

    Same dimensions, no compression between them, so this is direct pixel
    subtraction at a low threshold with no registration wanted or needed.
    """
    score = _diff_score(ref_a, ref_b,
                        cfg["reference_luma_threshold"],
                        cfg["reference_chroma_threshold"],
                        cfg.get("reference_tolerance_radius", 0))
    mask = changed_mask(score, 1.0, cfg["morph_open"])
    regions = _extract_regions(mask, cfg["min_region_area_fraction"],
                               cfg["morph_close"])
    return _collapse_if_global(
        regions, mask.shape[1], mask.shape[0],
        cfg.get("global_change_min_regions", 20),
        cfg.get("global_change_area_fraction", 0.25))
