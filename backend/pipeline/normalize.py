"""Compatibility shim — the implementation now lives in `core.imaging`.

The normalization primitives were domain-agnostic all along: nothing in them knows
about artwork, SKUs or versions. They moved to `core.imaging.loader` and
`core.imaging.geometry`, where they take explicit numbers instead of a threshold
dict and can be reused and tested on their own.

This module keeps the old names and the old dict-taking signatures so existing
callers keep working. New code should import from `core.imaging` directly.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from core.imaging.geometry import (  # noqa: F401  (re-exported)
    NormalizedImage,
    align_translation,
    detect_border_crop,
    detect_content_rect,
    extract_content,
    normalize_image,
    resize_area,
    shift_image,
)
from core.imaging.geometry import prepare_pair as _prepare_pair
from core.imaging.loader import load_rgb, sha256_file, to_ycrcb  # noqa: F401

__all__ = [
    "NormalizedImage", "align_translation", "crop_border", "detect_border_crop",
    "detect_content_rect", "extract_content", "load_rgb", "normalize_scraped",
    "prepare_pair", "resize_area", "sha256_file", "shift_image", "to_ycrcb",
]


def crop_border(img: np.ndarray, tolerance: int, max_fraction: float) -> np.ndarray:
    x, y, w, h = detect_border_crop(img, tolerance, max_fraction)
    return img[y:y + h, x:x + w]


def normalize_scraped(path: str | Path, cfg) -> NormalizedImage:
    """Decode and de-pad, reading the two thresholds out of a config mapping."""
    return normalize_image(path, cfg["border_uniform_tolerance"],
                           cfg["max_border_crop_fraction"])


def prepare_pair(scraped: np.ndarray, reference: np.ndarray,
                 cfg=None) -> tuple[np.ndarray, np.ndarray, float]:
    """Bring both images to a common working size and align.

    `cfg` is accepted and ignored — it was never read — so existing three-argument
    callers keep working.
    """
    return _prepare_pair(scraped, reference)
