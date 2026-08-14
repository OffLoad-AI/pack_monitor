"""Stage 0 — load and normalize.

Reuses `core/imaging/loader.py` and `geometry.py` unchanged: decode, ICC to sRGB,
flatten alpha onto white, de-pad. None of what a marketplace does to an image —
padding it into a square, converting its colour profile, flattening transparency
— is a real difference, so it is undone before anything is measured.

The images are deliberately **not** resized to a common size here. Registration
handles scale, and forcing a resize first destroys information the homography
needs: an 800px marketplace image upscaled to a 1500px reference has no more
detail than it did, but it does have interpolated edges that shift keypoints.
"""

from __future__ import annotations

import cv2
import numpy as np

from ..imaging.geometry import normalize_image
from ..trace import OK, StageTrace
from ..types import PairContext
from .base import register


class LoadNormalizeStage:
    name = "load_normalize"

    def applicable(self, ctx: PairContext) -> bool:
        return True

    def run(self, ctx: PairContext) -> StageTrace:
        t = StageTrace(stage=self.name, status=OK)
        cfg = ctx.config.normalize

        ref = normalize_image(ctx.reference_path, cfg.border_uniform_tolerance,
                              cfg.max_border_crop_fraction)
        mkt = normalize_image(ctx.marketplace_path, cfg.border_uniform_tolerance,
                              cfg.max_border_crop_fraction)

        ctx.reference_rgb = ref.rgb
        ctx.marketplace_rgb = mkt.rgb

        rec = ctx.recorder
        rec.write_image(t, "reference_normalized", ref.rgb)
        rec.write_image(t, "marketplace_normalized", mkt.rgb)
        rec.write_image(t, "reference_padding", _padding_overlay(ctx.reference_path, ref))
        rec.write_image(t, "marketplace_padding", _padding_overlay(ctx.marketplace_path, mkt))

        ref_stripped = _stripped_fraction(ref)
        mkt_stripped = _stripped_fraction(mkt)

        t.metric(
            reference_raw_size=list(ref.raw_size),
            reference_content_size=list(ref.content_size),
            reference_crop_box=list(ref.crop_box),
            reference_padding_stripped_fraction=ref_stripped,
            marketplace_raw_size=list(mkt.raw_size),
            marketplace_content_size=list(mkt.content_size),
            marketplace_crop_box=list(mkt.crop_box),
            marketplace_padding_stripped_fraction=mkt_stripped,
        )

        t.note(f"Read the reference at {ref.raw_size[0]}x{ref.raw_size[1]} pixels and "
               f"the marketplace image at {mkt.raw_size[0]}x{mkt.raw_size[1]}.")
        t.note("Both were converted to standard sRGB colour and any transparency was "
               "flattened onto white, which is what a marketplace does when it "
               "publishes an image.")

        if mkt_stripped > 0.001:
            t.note(f"Stripped {mkt_stripped * 100:.1f}% of the marketplace image as "
                   f"uniform padding, leaving {mkt.content_size[0]}x"
                   f"{mkt.content_size[1]} pixels of artwork.")
        else:
            t.note("The marketplace image had no uniform padding to strip.")

        if ref_stripped > 0.001:
            t.note(f"Stripped {ref_stripped * 100:.1f}% of the reference as uniform "
                   f"padding.")

        t.note("The two images were left at their own sizes on purpose. Aligning them "
               "comes next, and it works better on the original detail than on a "
               "resized copy.")
        return t


def _stripped_fraction(norm) -> float:
    raw_w, raw_h = norm.raw_size
    content_w, content_h = norm.content_size
    raw_area = float(raw_w * raw_h)
    if raw_area <= 0:
        return 0.0
    return max(0.0, 1.0 - (content_w * content_h) / raw_area)


def _padding_overlay(path, norm) -> np.ndarray:
    """The original image with the kept region outlined and the padding dimmed.

    Showing the crop box on the *raw* image is the only way to make "we removed
    this and kept that" checkable at a glance — a before/after of two cropped
    images shows the result but not the decision.
    """
    from ..imaging.loader import load_rgb

    raw = load_rgb(path)
    x, y, w, h = norm.crop_box
    out = (raw.astype(np.float32) * 0.35 + 255.0 * 0.65).astype(np.uint8)
    out[y:y + h, x:x + w] = raw[y:y + h, x:x + w]
    thickness = max(2, int(round(max(raw.shape[:2]) / 400)))
    cv2.rectangle(out, (x, y), (x + w - 1, y + h - 1), (37, 99, 235), thickness)
    return out


register("load_normalize")(LoadNormalizeStage)
