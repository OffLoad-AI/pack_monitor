"""De-padding, resampling and alignment.

The one job of this module is to put two copies of the same artwork onto the same
pixel grid. Everything downstream assumes it succeeded: a scale error of a fraction
of a pixel haloes every glyph edge and swamps the signal the whole method depends
on, so the care taken here is not fussiness.

Functions take explicit numbers rather than a configuration object, so they can be
reused and tested on their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .loader import load_rgb


def _deviation_profiles(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-row and per-column mean absolute deviation from that line's own median.

    Deliberately not max-minus-min. JPEG and WebP ring for several pixels either
    side of a hard padding edge, and a max-minus-min test trips on that ringing,
    stopping the scan early by a different amount per encoder and per quality. The
    leftover sliver of padding becomes a scale error, which smears every glyph. A
    robust statistic ignores the few rung pixels and finds the true edge.
    """
    f = img.astype(np.float32)
    row_dev = np.abs(f - np.median(f, axis=1, keepdims=True)).mean(axis=(1, 2))
    col_dev = np.abs(f - np.median(f, axis=0, keepdims=True)).mean(axis=(0, 2))
    return row_dev, col_dev


def detect_border_crop(img: np.ndarray, tolerance: float, max_fraction: float,
                       profiles: tuple[np.ndarray, np.ndarray] | None = None
                       ) -> tuple[int, int, int, int]:
    """Scan inward from each edge while the row/column stays uniform.

    Deliberately colour-agnostic: it strips uniform bands whatever their colour and
    keeps going through colour changes. That is what makes the crop *consistent*
    between a padded marketplace copy and an unpadded reference — a rule keyed on
    "is it white" would strip the pad from one and nothing from the other, leaving
    the two at different scales.

    `profiles` lets a caller that has already measured them pass them in; they cost
    two medians over the whole image and were previously computed twice per file.
    """
    h, w = img.shape[:2]
    max_y = int(h * max_fraction)
    max_x = int(w * max_fraction)
    row_dev, col_dev = profiles if profiles is not None else _deviation_profiles(img)

    top = 0
    while top < max_y and row_dev[top] <= tolerance:
        top += 1
    bottom = h - 1
    while bottom > h - 1 - max_y and row_dev[bottom] <= tolerance:
        bottom -= 1
    left = 0
    while left < max_x and col_dev[left] <= tolerance:
        left += 1
    right = w - 1
    while right > w - 1 - max_x and col_dev[right] <= tolerance:
        right -= 1

    if right <= left or bottom <= top:
        return 0, 0, w, h
    return left, top, right - left + 1, bottom - top + 1


def _subpixel_edge(profile: np.ndarray, index: int, descending: bool) -> float:
    """Where the uniformity profile crosses half its content-side level.

    The integer scan can only say "this row is content and the one before it was
    padding", so it carries up to half a pixel of error. Marketplace padding rarely
    lands on a whole pixel: a 1500px canvas padded by an eighth and resized to 800
    puts the true edge at 66.67. At 800px that residual is the largest single source
    of leftover difference.

    The crossing is measured at the midpoint between the padding level and the
    content level, not at the detection tolerance. Downscaling smears the boundary
    over two or three pixels, and a low fixed threshold is tripped by the leading
    edge of that ramp, biasing the estimate outward by more than the error it was
    meant to remove.
    """
    step = -1 if descending else 1
    n = profile.size

    def sample(i: int) -> float:
        return float(profile[min(max(i, 0), n - 1)])

    outer = [sample(index - step * k) for k in range(1, 5)]   # padding side
    inner = [sample(index + step * k) for k in range(0, 4)]   # content side
    base = float(np.median(outer))
    plateau = float(np.median(inner))
    if plateau <= base:
        return float(index)

    target = (base + plateau) / 2.0
    for k in range(0, 5):
        hi_i = index + step * (1 - k)
        lo_i = hi_i - step
        hi, lo = sample(hi_i), sample(lo_i)
        if lo <= target <= hi and hi > lo:
            frac = (target - lo) / (hi - lo)
            return float(lo_i) + step * frac
    return float(index)


def detect_content_rect(img: np.ndarray, tolerance: float,
                        max_fraction: float) -> tuple[float, float, float, float]:
    """The content rectangle as floats, refined past the integer scan."""
    # Measured once and shared with the integer scan below: these are two medians
    # over the full image, and computing them twice per file cost about a quarter
    # of normalization time.
    row_dev, col_dev = _deviation_profiles(img)

    x, y, w, h = detect_border_crop(img, tolerance, max_fraction,
                                    profiles=(row_dev, col_dev))
    if (x, y, w, h) == (0, 0, img.shape[1], img.shape[0]):
        return 0.0, 0.0, float(img.shape[1]), float(img.shape[0])

    top = _subpixel_edge(row_dev, y, descending=False) if y > 0 else 0.0
    bottom = (_subpixel_edge(row_dev, y + h - 1, descending=True)
              if y + h < img.shape[0] else float(img.shape[0] - 1))
    left = _subpixel_edge(col_dev, x, descending=False) if x > 0 else 0.0
    right = (_subpixel_edge(col_dev, x + w - 1, descending=True)
             if x + w < img.shape[1] else float(img.shape[1] - 1))

    return left, top, max(1.0, right - left + 1.0), max(1.0, bottom - top + 1.0)


def extract_content(img: np.ndarray,
                    rect: tuple[float, float, float, float]) -> np.ndarray:
    """Resample the float content rectangle onto a whole-pixel grid.

    The scale is within a pixel of 1:1, so this is a sub-pixel *shift* rather than a
    resize and bilinear is the right filter. Whole-pixel rectangles take a plain
    slice. Downscaling to a common working size happens later, with INTER_AREA.
    """
    x, y, w, h = rect
    out_w = int(round(w))
    out_h = int(round(h))
    if abs(x - round(x)) < 1e-3 and abs(y - round(y)) < 1e-3 and \
            abs(w - out_w) < 1e-3 and abs(h - out_h) < 1e-3:
        xi, yi = int(round(x)), int(round(y))
        return img[yi:yi + out_h, xi:xi + out_w]

    m = np.float32([[out_w / w, 0, -x * (out_w / w)],
                    [0, out_h / h, -y * (out_h / h)]])
    return cv2.warpAffine(img, m, (out_w, out_h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)


def resize_area(img: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """INTER_AREA on both sides, always.

    Both images go to the *smaller* of the two dimensions rather than up to the
    reference's. INTER_AREA degenerates to nearest-neighbour when upscaling, so
    resizing an 800px listing up to a 1500px reference manufactures blocky edge
    differences everywhere. Downscaling the reference mirrors what the marketplace
    CDN actually did and keeps interpolation identical on both sides.
    """
    if (img.shape[1], img.shape[0]) == size:
        return img
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA)


def align_translation(ref_gray: np.ndarray, img_gray: np.ndarray,
                      max_shift: int = 24) -> tuple[int, int]:
    """Recover an integer (dx, dy) by phase correlation.

    No keypoints and no homography: these are re-encoded copies of one file, not
    photographs of a pack. Sub-pixel offsets are rounded so runs are reproducible.
    """
    a = ref_gray.astype(np.float64)
    b = img_gray.astype(np.float64)
    win = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_64F)
    (dx, dy), _response = cv2.phaseCorrelate(a, b, win)
    dx_i = int(round(dx))
    dy_i = int(round(dy))
    if abs(dx_i) > max_shift or abs(dy_i) > max_shift:
        return 0, 0
    return dx_i, dy_i


def shift_image(img: np.ndarray, dx: int, dy: int) -> np.ndarray:
    if dx == 0 and dy == 0:
        return img
    m = np.float32([[1, 0, -dx], [0, 1, -dy]])
    return cv2.warpAffine(
        img, m, (img.shape[1], img.shape[0]),
        flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE,
    )


# eq=False: the generated __eq__ would compare the numpy field elementwise and
# raise on the truth value of the resulting array. Identity comparison is correct
# for this type anyway.
@dataclass(frozen=True, eq=False)
class NormalizedImage:
    """A decoded, de-padded image ready to be compared against references."""

    rgb: np.ndarray
    raw_size: tuple[int, int]
    crop_box: tuple[int, int, int, int]

    @property
    def content_size(self) -> tuple[int, int]:
        return self.rgb.shape[1], self.rgb.shape[0]


def normalize_image(path: str | Path, border_tolerance: float,
                    max_border_fraction: float) -> NormalizedImage:
    """Decode, colour-correct, flatten alpha and strip padding.

    Resizing and alignment deliberately happen later, per-reference, because the
    working size depends on which reference is being compared against.
    """
    rgb = load_rgb(path)
    raw_size = (rgb.shape[1], rgb.shape[0])
    rect = detect_content_rect(rgb, border_tolerance, max_border_fraction)
    content = extract_content(rgb, rect)
    box = (int(round(rect[0])), int(round(rect[1])),
           content.shape[1], content.shape[0])
    return NormalizedImage(content, raw_size, box)


def prepare_pair(probe: np.ndarray,
                 reference: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Bring two images to a common working size and align them.

    Returns `(probe_work, reference_work, scale)`, where `scale` maps reference
    pixel coordinates into working coordinates.
    """
    sw, sh = probe.shape[1], probe.shape[0]
    rw, rh = reference.shape[1], reference.shape[0]
    work_w = min(sw, rw)
    work_h = min(sh, rh)

    s = resize_area(probe, (work_w, work_h))
    r = resize_area(reference, (work_w, work_h))

    s_gray = cv2.cvtColor(s, cv2.COLOR_RGB2GRAY)
    r_gray = cv2.cvtColor(r, cv2.COLOR_RGB2GRAY)
    dx, dy = align_translation(r_gray, s_gray)
    if dx or dy:
        s = shift_image(s, dx, dy)

    return s, r, work_w / rw
