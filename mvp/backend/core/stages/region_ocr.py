"""Stage 4 — region OCR.

For each region proposed by the structural diff, crop from **both** images and
read each side. Tight crops are read badly, and for two separate reasons that
want two separate fixes. The region box clips the word it found, so the crop
reaches beyond it by a couple of line heights to recover the whole word. And a
detector trained on document scans treats a glyph flush against the image edge
as a partial glyph, so a white quiet zone goes around the crop immediately
before reading — added there rather than to the crop itself, because the crop
artefact the UI shows should be the region as it actually is.

The reference crop is taken from the **original reference**, not from the warped
copy. The warp resamples the reference into the marketplace frame, which on a
downscaled listing throws away exactly the resolution the reference had and the
marketplace lacked. Mapping the region box back through the inverse homography
costs one matrix multiply and reads the reference at its own resolution.

**Calibrating OCR against itself.** With one reference and one marketplace image
there is no second opinion available anywhere in the system — no other candidate
to rank against, no second version to diff. The only remaining source of evidence
about whether a reading is trustworthy is the reader's own stability: read the
same crop twice at different scales, and if the two readings disagree, the reading
is not evidence. Any text difference in such a region routes to `UNCERTAIN`, never
to a positive finding. This is not optional; it is the one mechanism available.

It is, however, only run where its answer can matter. A region whose two sides
already compare as no difference reaches `NO_DIFFERENCE` in stage 5 before that
stage consults reliability at all, so the second read there is work whose result
is discarded before it is read. Skipping it is not a trade against accuracy.
"""

from __future__ import annotations

import cv2
import numpy as np

from ..textnorm import compare_text, normalize
from ..trace import DEGRADED, OK, StageTrace
from ..types import KIND_PALETTE, NO_DIFFERENCE, OcrReading, PairContext
from .base import register


class RegionOcrStage:
    name = "region_ocr"

    def applicable(self, ctx: PairContext) -> bool:
        return bool(ctx.regions)

    def run(self, ctx: PairContext) -> StageTrace:
        t = StageTrace(stage=self.name, status=OK)
        cfg = ctx.config.ocr
        # Stage 5's thresholds, read here so the re-read gate below asks exactly
        # the question stage 5 will ask. A gate using different tolerances could
        # skip a re-read stage 5 then turns out to need.
        tcfg = ctx.config.text
        rec = ctx.recorder
        engine = ctx.ocr

        h_inv = None
        if ctx.homography is not None:
            try:
                h_inv = np.linalg.inv(ctx.homography)
            except np.linalg.LinAlgError:
                h_inv = None

        unreliable = 0
        read_ok = 0
        reads = 0
        skipped = 0
        skipped_rereads = 0
        confidences: list[float] = []

        for i, region in enumerate(ctx.regions, start=1):
            mkt_crop = _crop(ctx.marketplace_rgb, region.box, cfg.crop_pad_fraction,
                             cfg.crop_pad_line_heights)
            ref_crop = _reference_crop(ctx, region.box, cfg.crop_pad_fraction, h_inv,
                                       cfg.crop_pad_line_heights)

            # A collapsed whole-frame recolour has nothing to read: the text is
            # unchanged by definition of how the region was proposed, and OCR-ing
            # an entire pack front costs seconds to confirm it.
            if region.kind == KIND_PALETTE:
                skipped += 1
                region.reference_text = ""
                region.marketplace_text = ""
                region.ocr_reliable = True
                region.ref_crop_path = rec.write_image(
                    t, f"region_{i:02d}_reference", ref_crop)
                region.mkt_crop_path = rec.write_image(
                    t, f"region_{i:02d}_marketplace", mkt_crop)
                continue

            ref_scale = _upscale_factor(ref_crop, cfg)
            mkt_scale = _upscale_factor(mkt_crop, cfg)
            ref_reading = _read(engine, ref_crop, ref_scale, cfg.quiet_zone_px)
            mkt_reading = _read(engine, mkt_crop, mkt_scale, cfg.quiet_zone_px)
            reads += 2

            # The self-consistency pass, applied to **both** sides. The spec
            # calls for re-reading the reference; the marketplace image is the
            # degraded one, so checking only the reference checks the easy side.
            # Measured: a glare-damaged crop read "coffee ee" against "Coffee"
            # and would have been reported as a material change.
            # It considers *either* side having found text, not only the side
            # that read something: text on one side and nothing on the other is
            # the case that matters most, since it reads as a removal and is
            # usually just a failed read.
            any_text = bool(normalize(ref_reading.text) or normalize(mkt_reading.text))

            # The re-read only earns its cost where its answer can change the
            # verdict, and there is exactly one case where it cannot: when the
            # two sides already compare as no difference at all. Stage 5 tests
            # `difference_type == NO_DIFFERENCE` *before* it tests either
            # `ink_intact` or `ocr_reliable`, so such a region lands on
            # NO_DIFFERENCE whatever this flag says. Skipping the re-read there
            # is not a trade of accuracy for speed; it removes work whose result
            # was already discarded. It halves the OCR calls on a typical pair,
            # because the diff stage over-proposes on purpose and most proposed
            # regions do read the same on both sides.
            verdict_relevant = any_text and compare_text(
                ref_reading.text, mkt_reading.text,
                numeric_relative_tolerance=tcfg.numeric_relative_tolerance,
                confusable_max_distance=tcfg.confusable_max_distance,
            ).difference_type != NO_DIFFERENCE

            stable = True
            if verdict_relevant:
                ref_check = _read(engine, ref_crop, ref_scale * cfg.consistency_scale,
                                  cfg.quiet_zone_px)
                mkt_check = _read(engine, mkt_crop, mkt_scale * cfg.consistency_scale,
                                  cfg.quiet_zone_px)
                reads += 2
                stable = (normalize(ref_reading.text) == normalize(ref_check.text)
                          and normalize(mkt_reading.text) == normalize(mkt_check.text))
            else:
                skipped_rereads += 1

            low_confidence = min(ref_reading.min_confidence,
                                 mkt_reading.min_confidence) < cfg.min_token_confidence

            # Text on one side and nothing on the other is either a removal or a
            # failed read, and the strings alone cannot tell them apart. The
            # pixels can: if the unread side still has as much ink in it as the
            # read side, the text is there and the reader missed it.
            asymmetric = bool(normalize(ref_reading.text)) != bool(
                normalize(mkt_reading.text))
            # Measured over the region itself, not over the padded reading crop:
            # the padding is unchanged artwork by construction and only dilutes
            # the ratio, which turns a genuine removal into "the reader missed
            # it". The reading crop and the ink crop answer different questions.
            ink_kept = None
            if asymmetric:
                ref_box = _mapped_reference_box(ctx, region.box, h_inv)
                ink_kept = _ink_ratio(
                    _box_crop(ctx.reference_rgb, ref_box) if ref_box is not None
                    else _box_crop(ctx.warped_reference, region.box),
                    _box_crop(ctx.marketplace_rgb, region.box))
            unread_not_blank = bool(
                asymmetric and ink_kept is not None
                and ink_kept >= cfg.asymmetric_ink_ratio)

            region.reference_reading = ref_reading
            region.marketplace_reading = mkt_reading
            region.reference_text = ref_reading.text
            region.marketplace_text = mkt_reading.text
            region.ink_intact = unread_not_blank
            region.ocr_reliable = bool(engine.available and stable
                                       and not low_confidence
                                       and not unread_not_blank)

            if not region.ocr_reliable:
                unreliable += 1
            if ref_reading.text or mkt_reading.text:
                read_ok += 1
            confidences.extend([tok.confidence for tok in ref_reading.tokens])
            confidences.extend([tok.confidence for tok in mkt_reading.tokens])

            region.ref_crop_path = rec.write_image(
                t, f"region_{i:02d}_reference", _display(ref_crop))
            region.mkt_crop_path = rec.write_image(
                t, f"region_{i:02d}_marketplace", _display(mkt_crop))

        mean_confidence = float(np.mean(confidences)) if confidences else None
        readable = len(ctx.regions) - skipped
        t.metric(engine=engine.name, engine_available=engine.available,
                 regions_read=readable,
                 regions_skipped=skipped,
                 ocr_calls=reads,
                 consistency_rereads_skipped=skipped_rereads,
                 regions_with_text=read_ok,
                 regions_ocr_unreliable=unreliable,
                 mean_token_confidence=mean_confidence,
                 crop_pad_fraction=cfg.crop_pad_fraction,
                 quiet_zone_px=cfg.quiet_zone_px,
                 det_limit_side_len=cfg.det_limit_side_len,
                 consistency_scale=cfg.consistency_scale)

        # Confidence here is the share of regions whose reading is trustworthy.
        t.confidence = (round(1.0 - unreliable / readable, 4) if readable else None)

        if not engine.available:
            t.status = DEGRADED
            t.note("No OCR engine is installed, so nothing could be read. Every "
                   "region is therefore marked unreliable and any difference will "
                   "be reported as needing review rather than as a finding.")
            t.note("Install one with: pip install rapidocr-onnxruntime")
            return t

        t.note(f"Read {readable} region(s) with {engine.name} over {reads} passes, "
               f"cropping each from both images with generous padding so that a word "
               f"is never cut in half.")
        t.note(f"Text was found in {read_ok} of {readable} region(s). A region with no "
               f"text on either side is a purely visual change — a mark or a logo — "
               f"and is still reported.")
        if skipped:
            t.note(f"{skipped} whole-pack colour change was not read: a recolour has "
                   f"no text of its own, and any text change would have shown up as "
                   f"its own region.")

        if unreliable:
            t.status = DEGRADED
            t.note(f"{unreliable} region(s) read differently when re-read at another "
                   f"scale, or contained low-confidence characters. Those readings "
                   f"are not treated as evidence: any difference found in them is "
                   f"reported as needing review.")
        else:
            t.note("Every region read identically when re-read at a different scale, "
                   "which is the only check available that the reading is stable.")

        if skipped_rereads:
            t.note(f"{skipped_rereads} region(s) read the same on both sides, so the "
                   f"stability check was not run on them: there is no difference for "
                   f"it to confirm or overturn.")

        return t


# --------------------------------------------------------------------------


def _crop(img: np.ndarray, box, pad_fraction: float,
          pad_line_heights: float = 2.0) -> np.ndarray:
    """Crop with padding measured against the region's *height*, not its width.

    A proportional 10% pad gives a 25px-tall box 2.5px of room, which is not
    enough to recover a word the region clipped — and a clipped word is read as
    nonsense, which becomes a false material finding. Region height is a good
    proxy for line height, so padding horizontally by a couple of line heights
    reliably captures the whole word. Vertically the pad stays small, because
    growing vertically pulls in the line above and below.

    The multiplier is not free either way. Measured on a REENCODED pair whose
    region clipped the F of "Flakes": at 1.2 line heights the reference read
    "lakes" against the marketplace's "Flakes", which the ladder classifies as
    TEXT_CHANGED and therefore reports unchanged artwork as DIFFERENT. By 3.0 the
    crop has reached the neighbouring word. The default sits mid-band.
    """
    x, y, w, h = box
    # `h` stands in for line height, but only while the region is roughly
    # line-shaped. A 4x193 sliver at a de-padding boundary has no line height at
    # all, and padding it by 1.2 x 193 sweeps in a whole column of the nutrition
    # table — measured: that produced a false material finding on unchanged
    # artwork. Capping the stand-in at twice the region width keeps the
    # word-recovery behaviour for text and neutralises it for slivers.
    line_height = min(h, max(w * 2, 8))
    px = max(int(round(w * pad_fraction)),
             int(round(line_height * pad_line_heights))) + 2
    py = max(int(round(h * pad_fraction)), int(round(h * 0.25))) + 2
    x0 = max(0, x - px)
    y0 = max(0, y - py)
    x1 = min(img.shape[1], x + w + px)
    y1 = min(img.shape[0], y + h + py)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((1, 1, 3), np.uint8)
    return img[y0:y1, x0:x1]


def _box_crop(img: np.ndarray, box) -> np.ndarray:
    """The region exactly, with no padding at all.

    What the ink guard measures. The reading crop deliberately reaches past the
    region to recover a clipped word, and that extra artwork is unchanged by
    definition — it was not part of what the diff proposed. Measuring edge
    energy over it dilutes the very signal the guard exists to detect: measured
    on a CERT_REMOVED pair, a removed mark that dropped the region's own edge
    energy well below the threshold still left the *padded* crop at 0.79,
    which the guard read as "the printing is still there, the reader missed it"
    and the pair was reported as MATCH.
    """
    x, y, w, h = box
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(img.shape[1], x + w), min(img.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((1, 1, 3), np.uint8)
    return img[y0:y1, x0:x1]


def _mapped_reference_box(ctx: PairContext, box,
                          h_inv: np.ndarray | None) -> tuple | None:
    """The region box in reference coordinates, or None if it does not map."""
    if h_inv is None or ctx.reference_rgb is None:
        return None
    x, y, w, h = box
    corners = np.float32([[x, y], [x + w, y], [x + w, y + h],
                          [x, y + h]]).reshape(-1, 1, 2)
    mapped = cv2.perspectiveTransform(corners, h_inv).reshape(-1, 2)
    x0, y0 = mapped.min(axis=0)
    x1, y1 = mapped.max(axis=0)
    rw, rh = int(round(x1 - x0)), int(round(y1 - y0))
    if rw < 2 or rh < 2:
        return None
    return int(round(x0)), int(round(y0)), rw, rh


def _reference_crop(ctx: PairContext, box, pad_fraction: float,
                    h_inv: np.ndarray | None,
                    pad_line_heights: float = 2.0) -> np.ndarray:
    """Map the box back into reference coordinates and crop at full resolution.

    Falls back to the warped copy if the homography is not invertible, which
    should be impossible after the registration stage's condition-number gate but
    is cheap to guard.
    """
    ref_box = _mapped_reference_box(ctx, box, h_inv)
    if ref_box is None:
        return _crop(ctx.warped_reference, box, pad_fraction, pad_line_heights)
    return _crop(ctx.reference_rgb, ref_box, pad_fraction, pad_line_heights)


def _ink_ratio(ref_crop: np.ndarray, mkt_crop: np.ndarray) -> float | None:
    """How much of the reference crop's edge detail survives in the marketplace one.

    "Ink" here is edge energy — the mean absolute Laplacian response. Printed
    text is almost entirely edges, so a crop that lost its text loses most of its
    edge energy, while a crop whose text was merely misread keeps it. This is the
    only evidence available for telling a removal apart from a failed read, since
    the strings themselves say the same thing in both cases.

    Returns the marketplace-to-reference ratio, or None if the reference crop had
    no detail to lose.
    """
    if ref_crop is None or mkt_crop is None or ref_crop.size == 0 or mkt_crop.size == 0:
        return None

    def energy(crop: np.ndarray) -> float:
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        return float(np.abs(cv2.Laplacian(gray, cv2.CV_32F, ksize=3)).mean())

    ref_energy = energy(ref_crop)
    if ref_energy < 1e-3:
        return None
    return energy(mkt_crop) / ref_energy


def _upscale_factor(crop: np.ndarray, cfg) -> float:
    """Small text recognizes far better upscaled, and cost is irrelevant here."""
    long_edge = max(crop.shape[:2])
    if long_edge >= cfg.min_long_edge:
        return 1.0
    return float(min(cfg.upscale_max, cfg.min_long_edge / max(1, long_edge)))


def _read(engine, crop: np.ndarray, scale: float, quiet_zone_px: int = 0) -> OcrReading:
    """Scale the crop, surround it with a white quiet zone, and read it.

    The quiet zone is added here rather than in `_crop` on purpose: the crop
    artefact written for the UI should show the region as it actually is, and
    the margin is a property of what the detector needs, not of what the region
    contains. Measured on this pipeline's own crops, tight against the text:
    "27. 7.5" for "27.5", "15. 6" for "15.6", "5 6.9" for "5.9" — each of which
    is a token count mismatch, and therefore a material finding, on artwork
    where nothing changed. With the margin all three read correctly.
    """
    if crop is None or crop.size == 0:
        return OcrReading(text="", tokens=[])
    img = crop
    if scale != 1.0:
        w = max(1, int(round(crop.shape[1] * scale)))
        h = max(1, int(round(crop.shape[0] * scale)))
        # A hard cap: a 3x upscale of an already-large crop is wasted work, and
        # some recognizers degrade above their training resolution.
        if max(w, h) <= 2400:
            img = cv2.resize(crop, (w, h), interpolation=cv2.INTER_CUBIC)
    if quiet_zone_px > 0:
        img = cv2.copyMakeBorder(img, quiet_zone_px, quiet_zone_px,
                                 quiet_zone_px, quiet_zone_px,
                                 cv2.BORDER_CONSTANT, value=(255, 255, 255))
    return engine.read(img)


def _display(crop: np.ndarray) -> np.ndarray:
    """Magnify tiny crops for the UI.

    A 40x14px crop of a changed digit is unreadable at screen scale, and the
    whole point of showing it is that a person can check the reading themselves.
    Nearest-neighbour on purpose: it shows the pixels as they are rather than
    inventing smooth edges that suggest detail the image does not have.
    """
    h, w = crop.shape[:2]
    if max(h, w) >= 240 or min(h, w) < 1:
        return crop
    s = min(6, max(2, int(round(240 / max(1, max(h, w))))))
    return cv2.resize(crop, (w * s, h * s), interpolation=cv2.INTER_NEAREST)


register("region_ocr")(RegionOcrStage)
