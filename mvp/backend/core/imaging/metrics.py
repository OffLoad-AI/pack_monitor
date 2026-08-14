"""Difference metrics.

The statistics the engine ranks candidates on. Each takes explicit thresholds so
it can be reused, tested and recalibrated independently of any configuration
object or domain.
"""

from __future__ import annotations

import cv2
import numpy as np

from .loader import to_ycrcb


def diff_channels(a_rgb: np.ndarray, b_rgb: np.ndarray,
                  tolerance_radius: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel luma and chroma differences, in 0..255.

    `tolerance_radius` compares each probe pixel against the *range* of reference
    values in its r-pixel neighbourhood, scoring zero if it falls inside that band.
    This is the single most important trick in the pipeline: letterbox padding can
    only ever be located to about a pixel, and the resulting sub-pixel scale error
    puts a one-pixel halo around every glyph. Without the band those halos dominate
    the diff and drown the signal; with it they score zero, while a changed digit —
    which differs over a blob several pixels across — still scores full.
    """
    a = to_ycrcb(a_rgb).astype(np.int16)
    b = to_ycrcb(b_rgb)

    if tolerance_radius > 0:
        k = cv2.getStructuringElement(
            cv2.MORPH_RECT, (2 * tolerance_radius + 1, 2 * tolerance_radius + 1))
        b_hi = cv2.dilate(b, k).astype(np.int16)
        b_lo = cv2.erode(b, k).astype(np.int16)
        d = np.maximum(np.maximum(a - b_hi, b_lo - a), 0)
    else:
        d = np.abs(a - b.astype(np.int16))

    luma = d[:, :, 0].astype(np.float32)
    chroma = np.maximum(d[:, :, 1], d[:, :, 2]).astype(np.float32)
    return luma, chroma


def diff_score(a_rgb: np.ndarray, b_rgb: np.ndarray, luma_threshold: float,
               chroma_threshold: float, tolerance_radius: int = 1) -> np.ndarray:
    """Normalized difference: 1.0 means "exactly at the threshold".

    Each channel is divided by its own calibrated threshold before the max is
    taken, which makes every downstream comparison threshold-free.

    The two thresholds are separate because the noise floors differ by almost a
    factor of three. JPEG subsamples chroma 4:2:0 but spends most of its bits on
    luma edges, so luma noise is dominated by text outlines while chroma noise is
    comparatively flat. A single threshold taken from the luma floor is blind to a
    palette change: a 15-degree hue rotation moves chroma by ~10 and luma by ~5.
    """
    luma, chroma = diff_channels(a_rgb, b_rgb, tolerance_radius)
    return np.maximum(luma / float(luma_threshold),
                      chroma / float(chroma_threshold))


def changed_mask(score: np.ndarray, threshold: float = 1.0,
                 morph_open: int = 3) -> np.ndarray:
    """Threshold, then open away isolated speckle.

    Compression noise is salt-and-pepper at the pixel level; a real edit is a
    connected blob several pixels across. A 3x3 open removes most of the former and
    almost none of the latter, and is where much of the separation margin between
    the two distributions comes from.
    """
    mask = (score > threshold).astype(np.uint8)
    if morph_open and morph_open > 1:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (morph_open, morph_open))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    return mask


def changed_fraction(score: np.ndarray, threshold: float = 1.0,
                     morph_open: int = 3) -> float:
    mask = changed_mask(score, threshold, morph_open)
    return float(mask.sum()) / float(mask.size)


def region_signal(score: np.ndarray, box: tuple[int, int, int, int],
                  cap: float = 3.0, top_fraction: float = 0.05) -> float:
    """How different a region is: the mean of its most-changed pixels.

    This is the statistic candidate ranking uses, in preference to "fraction of
    pixels over threshold". Counting pixels over a threshold works for a changed
    word — a few pixels move a long way — but is nearly blind to a palette shift,
    where every pixel moves a little and lands just under the bar. Two versions
    differing only by a hue rotation score 0.0044 and 0.0045 by pixel count, a coin
    toss; by mean signal they score 0.24 and 1.68.

    Averaging only the top `top_fraction` is what keeps small edits legible on
    heavily downscaled listings. A changed digit occupies a few percent of its
    bounding box, so a plain mean buries it under the unchanged background sharing
    that box — worth about three points of accuracy at 800x800. The top slice still
    behaves correctly for a global recolour, where every pixel moved.

    `cap` stops one saturated region from dominating a sum, so a small text edit
    still registers against a large recoloured background.
    """
    x, y, w, h = box
    sub = score[y:y + h, x:x + w]
    if sub.size == 0:
        return 0.0
    clipped = np.clip(sub, 0.0, cap).reshape(-1)
    n = clipped.size
    k = max(1, int(n * top_fraction))
    if k >= n:
        return float(clipped.mean())
    # partition is O(n); this runs per candidate per region per image.
    return float(np.partition(clipped, n - k)[n - k:].mean())


def region_changed_fraction(score: np.ndarray, box: tuple[int, int, int, int],
                            threshold: float = 1.0, morph_open: int = 1) -> float:
    """Fraction of a region over threshold.

    The open defaults to 1 — none. Regions are small, and a 3x3 open erases a
    one-digit change entirely once the listing has been downscaled.
    """
    x, y, w, h = box
    sub = score[y:y + h, x:x + w]
    if sub.size == 0:
        return 0.0
    mask = (sub > threshold).astype(np.uint8)
    if morph_open and morph_open > 1 and min(sub.shape) > morph_open * 2:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (morph_open, morph_open))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    return float(mask.sum()) / float(mask.size)
