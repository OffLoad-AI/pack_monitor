"""Stage 3 — structural diff.

**SSIM over local windows, not absolute pixel difference.** Registration is never
pixel-exact, and illumination and white balance differences make raw subtraction
useless on a photographed pack — a slightly warmer light source moves every pixel
by more than a changed digit does. SSIM asks whether the local *structure* matches,
which survives both.

Two things about this stage are deliberate and easy to mistake for bugs.

**Chroma is compared separately from luma.** A pure palette change moves chroma
while barely moving luma, so an SSIM map computed on grayscale alone is blind to a
repainted pack. That was a real bug in the version-identification build, found by
measurement after 28 images came back unidentified; it is not reintroduced here.

**This stage is tuned for recall, not precision.** Its output is candidate regions
for OCR, not findings. A false region costs one OCR call. A missed region is
invisible forever. So the threshold sits near the 95th percentile of the
calibrated noise floor rather than the 99.9th, and the region list is expected to
contain junk that the OCR and text stages then throw away. This inverts the tuning
philosophy of the other build **at this stage only** — the refuse-rather-than-guess
principle still governs the final verdict.
"""

from __future__ import annotations

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from ..imaging.regions import extract_regions
from ..trace import OK, StageTrace
from ..types import KIND_PALETTE, KIND_PIXEL, MATCH, PairContext, RegionFinding
from .base import register


class StructuralDiffStage:
    name = "structural_diff"

    def applicable(self, ctx: PairContext) -> bool:
        return ctx.warped_reference is not None and ctx.overlap_mask is not None

    def run(self, ctx: PairContext) -> StageTrace:
        t = StageTrace(stage=self.name, status=OK)
        cfg = ctx.config.diff
        rec = ctx.recorder

        ref = ctx.warped_reference
        mkt = ctx.marketplace_rgb
        win = cfg.ssim_window if cfg.ssim_window % 2 == 1 else cfg.ssim_window + 1

        # The warp interpolates along the overlap boundary, and that seam is not a
        # change in the artwork. Eroding the valid mask before differencing costs
        # a few pixels of coverage and removes a guaranteed false region.
        valid = ctx.overlap_mask > 0
        if cfg.overlap_erode_px > 0:
            n = cfg.overlap_erode_px
            k = cv2.getStructuringElement(cv2.MORPH_RECT, (n * 2 + 1, n * 2 + 1))
            # `borderValue=0` is not the default. OpenCV erodes with a border
            # value of +infinity, so a mask that reaches the frame edge is not
            # eroded there at all — which is exactly where the artefacts are.
            # Measured: without this, the artwork's trim ticks and the de-padding
            # boundary proposed a dozen junk regions along every edge, and one of
            # them became a false material finding on unchanged artwork.
            valid = cv2.erode(valid.astype(np.uint8), k,
                              borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0

        # -- luma structure -------------------------------------------------
        ref_gray = cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY)
        mkt_gray = cv2.cvtColor(mkt, cv2.COLOR_RGB2GRAY)
        global_ssim, ssim_map = structural_similarity(
            ref_gray, mkt_gray, full=True, data_range=255, win_size=win)

        # SSIM runs -1..1. Half the complement puts "structurally identical" at 0
        # and "structurally opposite" at 1, which is the range the threshold and
        # the heatmap both want.
        d_ssim = np.clip((1.0 - ssim_map) / 2.0, 0.0, 1.0).astype(np.float32)

        # -- chroma ---------------------------------------------------------
        ref_cc = cv2.cvtColor(ref, cv2.COLOR_RGB2YCrCb).astype(np.float32)
        mkt_cc = cv2.cvtColor(mkt, cv2.COLOR_RGB2YCrCb).astype(np.float32)
        d_chroma = np.maximum(np.abs(ref_cc[:, :, 1] - mkt_cc[:, :, 1]),
                              np.abs(ref_cc[:, :, 2] - mkt_cc[:, :, 2]))
        # Averaged over the same window as SSIM so the two are locally comparable
        # statistics rather than a window measure and a point measure.
        d_chroma = cv2.blur(d_chroma, (win, win))

        # -- combine --------------------------------------------------------
        # Each channel divided by its own threshold before the max is taken, so
        # 1.0 means "exactly at the noise floor" in whichever channel spoke
        # loudest, and everything downstream is threshold-free.
        n_ssim = (d_ssim / float(cfg.ssim_threshold)).astype(np.float32)
        n_chroma = (d_chroma / float(cfg.chroma_threshold)).astype(np.float32)
        score = np.maximum(n_ssim, n_chroma)
        score[~valid] = 0.0
        ctx.diff_score = score

        overlap_area = float(valid.sum())
        mask_raw = ((score > 1.0) & valid).astype(np.uint8)
        mask_luma_raw = ((n_ssim > 1.0) & valid).astype(np.uint8)

        mask = _morphology(mask_raw, cfg)
        mask_luma = _morphology(mask_luma_raw, cfg)

        changed_area_fraction = (float(mask.sum()) / overlap_area
                                 if overlap_area > 0 else 0.0)
        mean_ssim_in_overlap = (float(ssim_map[valid].mean())
                                if overlap_area > 0 else 0.0)

        # -- is this a global recolour? --------------------------------------
        # A hue rotation moves colour everywhere and leaves the printing where it
        # was. Three conditions together, because no one of them is sufficient:
        #
        #   *spread*     the changed pixels reach across the frame, not into one
        #                corner. Measured as the union bounding box, following
        #                the other build's `collapse_if_global` — a recolour's
        #                changed *area* can be modest while its *reach* is total,
        #                because only the saturated parts of the pack clear the
        #                threshold.
        #   *count*      it decomposes into many components, one per coloured
        #                element, rather than into one edited box.
        #   *dominance*  the difference is colour rather than shape. This is what
        #                separates a recolour from a redesign.
        changed_px = mask_raw > 0
        chroma_dominant = (float((n_chroma[changed_px] > n_ssim[changed_px]).mean())
                           if changed_px.any() else 0.0)

        spread = _union_fraction(mask, overlap_area)
        component_count = int(cv2.connectedComponentsWithStats(mask, connectivity=8)[0]) - 1
        # A fourth condition, and it is what separates a repainted pack from a
        # photograph taken under a warm lamp. Both are chroma-dominant and both
        # reach across the frame; a hue rotation moves 9% of the area past the
        # threshold, a white-balance cast moves 0.4%. Measured on the corpus.
        palette = (spread >= cfg.global_change_area_fraction
                   and changed_area_fraction >= cfg.global_change_min_area_fraction
                   and component_count >= cfg.global_change_min_regions
                   and chroma_dominant >= cfg.chroma_dominance_fraction)

        # When it is a recolour, structural regions come from the **luma channel
        # alone**, so that a pack which was both recoloured and had a number
        # changed still reports the number. A recolour cannot hide an edit.
        source_mask = mask_luma if palette else mask

        # -- regions --------------------------------------------------------
        raw_regions = extract_regions(source_mask, min_area_fraction=0.0, morph_close=1)
        kept = []
        for r in raw_regions:
            frac = (r["w"] * r["h"]) / overlap_area if overlap_area > 0 else 0.0
            if frac < cfg.min_region_area_fraction:
                continue
            box = (r["x"], r["y"], r["w"], r["h"])
            kept.append(RegionFinding(
                box=box, area_fraction=frac, kind=KIND_PIXEL,
                signal=_box_signal(score, box)))

        # A cap, not a filter. A warped photograph can propose hundreds of
        # regions and OCR-ing all of them buys nothing; the largest carry the
        # information. Sorted back into reading order afterwards so the region
        # list is stable and scans top-to-bottom.
        capped = len(kept) > cfg.max_regions
        if capped:
            kept.sort(key=lambda r: (-r.area_fraction, r.box[1], r.box[0]))
            kept = kept[:cfg.max_regions]
        kept.sort(key=lambda r: (r.box[1], r.box[0], r.box[2], r.box[3]))

        if palette:
            ys, xs = np.nonzero(valid)
            kept.insert(0, RegionFinding(
                box=(int(xs.min()), int(ys.min()),
                     int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)),
                area_fraction=changed_area_fraction, kind=KIND_PALETTE,
                signal=float(score[changed_px].mean()) if changed_px.any() else 0.0))

        ctx.regions = kept

        # -- artefacts ------------------------------------------------------
        rec.write_image(t, "ssim_heatmap", _heatmap(d_ssim, valid))
        rec.write_image(t, "mask_raw", mask_raw * 255, lossless=True)
        rec.write_image(t, "mask_morphology", mask * 255, lossless=True)
        rec.write_image(t, "regions", _draw_boxes(mkt, kept))

        t.metric(global_ssim=float(global_ssim),
                 mean_ssim_in_overlap=mean_ssim_in_overlap,
                 regions_before_filter=len(raw_regions),
                 regions_after_filter=len(kept),
                 changed_area_fraction=changed_area_fraction,
                 chroma_dominant_fraction=chroma_dominant,
                 changed_spread_fraction=spread,
                 changed_components=component_count,
                 global_recolour=palette,
                 threshold_used=float(cfg.ssim_threshold),
                 chroma_threshold_used=float(cfg.chroma_threshold),
                 min_region_area_fraction=float(cfg.min_region_area_fraction),
                 region_cap_reached=capped)

        # Confidence here is coverage, not correctness: how much of the frame this
        # stage was actually able to inspect.
        t.confidence = float(round(min(1.0, overlap_area / float(score.size)), 4))

        t.note(f"Structural similarity across the shared area is "
               f"{mean_ssim_in_overlap:.4f}, where 1.0000 would mean structurally "
               f"identical.")
        t.note(f"{changed_area_fraction * 100:.2f}% of the shared area differs by more "
               f"than re-encoding alone can explain.")

        if palette:
            t.note(f"{chroma_dominant * 100:.0f}% of that difference is colour rather "
                   f"than shape, spread across the whole pack. That is what a "
                   f"repainted pack looks like, so it is reported as one change "
                   f"rather than as one per element.")
            t.note("Because a recolour must not be able to hide a changed number, the "
                   "regions below were taken from brightness alone, which a colour "
                   "change barely moves.")

        if not kept:
            t.note("No region survived filtering, so there is nothing for the reading "
                   "step to look at. On its own this reads as: the artwork matches.")
            ctx.halt(MATCH, "No changed region survived filtering, so there was "
                            "nothing to read or compare.")
            ctx.verdict = MATCH
            ctx.confidence = t.confidence
        else:
            t.note(f"Proposed {len(kept)} region(s) to read, from "
                   f"{len(raw_regions)} raw blob(s).")
            t.note("This step is deliberately generous — it is better to propose a "
                   "region that turns out to be nothing than to miss one. The reading "
                   "step decides what is real.")
        if capped:
            t.note(f"More than {cfg.max_regions} regions were proposed; only the "
                   f"largest {cfg.max_regions} are read.")

        return t


# --------------------------------------------------------------------------


def _union_fraction(mask: np.ndarray, overlap_area: float) -> float:
    """How far across the frame the changed pixels reach, as a fraction.

    Reach rather than area: fifty recoloured badges scattered over a pack cover
    little of it but span all of it, and that spread is what says "the whole pack
    moved" rather than "this box changed".
    """
    ys, xs = np.nonzero(mask)
    if xs.size == 0 or overlap_area <= 0:
        return 0.0
    span = (xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)
    return float(min(1.0, span / overlap_area))


def _morphology(mask: np.ndarray, cfg) -> np.ndarray:
    """Open away speckle, then close along the reading direction.

    The closing kernel is wide and short. A tall square kernel of the same width
    would bridge a nutrition table's rows into one blob; a narrow one leaves a
    changed word as three fragments, and a crop of a fragment reads as nonsense.
    """
    out = mask
    if cfg.morph_open > 1:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (cfg.morph_open,) * 2)
        out = cv2.morphologyEx(out, cv2.MORPH_OPEN, k)
    if cfg.morph_close_x > 1 or cfg.morph_close_y > 1:
        k = cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(1, cfg.morph_close_x), max(1, cfg.morph_close_y)))
        out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, k)
    return out


def _box_signal(score: np.ndarray, box) -> float:
    x, y, w, h = box
    sub = score[y:y + h, x:x + w]
    return float(sub.mean()) if sub.size else 0.0


def _heatmap(d: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """A perceptually ordered colourmap, never jet.

    Jet has bright bands in the middle of its range, so it invents structure that
    is not in the data — exactly the failure mode this screen exists to avoid.
    Inferno is monotonic in lightness: brighter genuinely means more different.
    """
    norm = np.clip(d / max(float(d[valid].max()) if valid.any() else 1.0, 1e-6),
                   0, 1)
    img = cv2.applyColorMap((norm * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img[~valid] = (245, 245, 245)
    return img


def _draw_boxes(mkt: np.ndarray, regions) -> np.ndarray:
    out = mkt.copy()
    thickness = max(2, int(round(max(out.shape[:2]) / 500)))
    for i, r in enumerate(regions):
        x, y, w, h = r.box
        cv2.rectangle(out, (x, y), (x + w, y + h), (37, 99, 235), thickness)
        cv2.putText(out, str(i + 1), (x, max(12, y - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (37, 99, 235), thickness)
    return out


register("structural_diff")(StructuralDiffStage)
