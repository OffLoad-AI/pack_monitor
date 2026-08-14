"""Stage 2 — registration.

This is the stage that makes the whole build worth having. The other build
compares re-encoded copies of one file and recovers alignment with phase
correlation, which is an integer translation and nothing more. That works only
while the marketplace image really is a copy of the brand's file. Registration by
keypoints and a homography works whether the marketplace image is a re-encoded
copy **or** a third-party photograph — it is slower and less accurate on the easy
case, and it is the only thing that works if the easy case turns out not to hold.

The rejection rules are the substance here. A homography that converged is not the
same as a homography that is any good: 18 inliers clustered in one corner will
produce a transform, and everything downstream will then treat two unrelated
images as aligned. So this stage rejects on **quality**, not merely on failure to
converge, and when it rejects it stops the pipeline rather than passing rubbish on.
"""

from __future__ import annotations

import cv2
import numpy as np

from ..trace import DEGRADED, FAILED, OK, StageTrace
from ..types import CANNOT_COMPARE, PairContext
from .base import register


class RegistrationStage:
    name = "registration"

    def applicable(self, ctx: PairContext) -> bool:
        return ctx.reference_rgb is not None and ctx.marketplace_rgb is not None

    def run(self, ctx: PairContext) -> StageTrace:
        t = StageTrace(stage=self.name, status=OK)
        cfg = ctx.config.registration
        rec = ctx.recorder

        ref = ctx.reference_rgb
        mkt = ctx.marketplace_rgb
        ref_gray = cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY)
        mkt_gray = cv2.cvtColor(mkt, cv2.COLOR_RGB2GRAY)

        # -- detect ---------------------------------------------------------
        detector_name, kp_ref, des_ref, kp_mkt, des_mkt = _detect(ref_gray, mkt_gray, cfg)
        t.metric(detector=detector_name,
                 keypoints_ref=len(kp_ref), keypoints_mkt=len(kp_mkt))

        if des_ref is None or des_mkt is None or len(kp_ref) < 4 or len(kp_mkt) < 4:
            return _refuse(ctx, t, "Almost no distinctive detail was found in one of "
                                   "the images, so there is nothing to line up.")

        # -- match ----------------------------------------------------------
        norm = cv2.NORM_HAMMING if detector_name == "ORB" else cv2.NORM_L2
        matcher = cv2.BFMatcher(norm)
        knn = matcher.knnMatch(des_ref, des_mkt, k=2)
        raw_count = len(knn)

        # Lowe's ratio test: a keypoint whose best match is barely better than its
        # second best is matching texture, not a landmark.
        good = [m for m, n in (p for p in knn if len(p) == 2)
                if m.distance < cfg.lowe_ratio * n.distance]
        t.metric(matches_raw=raw_count, matches_after_ratio=len(good))

        if len(good) < 4:
            return _refuse(ctx, t, "Fewer than four points could be matched between "
                                   "the two images, which is not enough to line them "
                                   "up at all.")

        src = np.float32([kp_ref[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp_mkt[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

        # -- fit ------------------------------------------------------------
        H, inlier_mask = cv2.findHomography(src, dst, cv2.RANSAC,
                                            cfg.ransac_reproj_px, maxIters=5000,
                                            confidence=0.999)
        if H is None or inlier_mask is None:
            return _refuse(ctx, t, "No single geometric transform could explain the "
                                   "matched points, so the two images do not show the "
                                   "same flat surface.")

        inliers = int(inlier_mask.sum())
        inlier_ratio = inliers / float(len(good))
        reproj = _reprojection_error(H, src, dst, inlier_mask)
        cond = float(np.linalg.cond(H))
        scale, rotation = _implied_transform(H)

        t.metric(inliers=inliers, inlier_ratio=inlier_ratio,
                 mean_reprojection_error=reproj, condition_number=cond,
                 implied_scale=scale, implied_rotation_deg=rotation)

        rec.write_image(t, "keypoint_matches",
                        _draw_matches(ref, mkt, kp_ref, kp_mkt, good, inlier_mask))

        # -- reject on quality ----------------------------------------------
        if inliers < cfg.inliers_required:
            return _refuse(ctx, t,
                           f"Only {inliers} points agreed on how the images line up. "
                           f"At least {cfg.inliers_required} are needed before the "
                           f"alignment can be trusted at all.")

        if not np.isfinite(cond) or cond > cfg.max_condition_number:
            return _refuse(ctx, t,
                           "The alignment collapses the reference onto a line rather "
                           "than mapping it onto the marketplace image. That is a "
                           "degenerate result, not a match.")

        if not (cfg.min_scale <= scale <= cfg.max_scale):
            return _refuse(ctx, t,
                           f"The alignment implies the reference would have to be "
                           f"resized {scale:.2f}x to fit, which is outside anything "
                           f"plausible for the same artwork.")

        # -- warp -----------------------------------------------------------
        h_mkt, w_mkt = mkt.shape[:2]
        warped = cv2.warpPerspective(ref, H, (w_mkt, h_mkt), flags=cv2.INTER_LINEAR,
                                     borderMode=cv2.BORDER_CONSTANT,
                                     borderValue=(255, 255, 255))
        valid = cv2.warpPerspective(np.full(ref.shape[:2], 255, np.uint8), H,
                                    (w_mkt, h_mkt), flags=cv2.INTER_NEAREST,
                                    borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        overlap_fraction = float((valid > 0).sum()) / float(valid.size)
        t.metric(overlap_fraction=overlap_fraction)

        if overlap_fraction < cfg.min_overlap_fraction:
            return _refuse(ctx, t,
                           f"After lining the images up, they only share "
                           f"{overlap_fraction * 100:.0f}% of the frame. Two views of "
                           f"the same pack overlap far more than that.")

        ctx.homography = H
        ctx.warped_reference = warped
        ctx.overlap_mask = valid

        # The matrix itself, so a caller can map a region box back into reference
        # coordinates — which is what the accuracy harness needs to check a
        # detected region against a ground-truth one, and what the OCR stage uses
        # to read the reference at its own resolution.
        t.metric(homography=[[float(v) for v in row] for row in H])

        rec.write_image(t, "warped_reference", warped)
        rec.write_image(t, "overlap_mask", valid, lossless=True)
        rec.write_image(t, "checkerboard", _checkerboard(warped, mkt, valid))

        # -- confidence -----------------------------------------------------
        # Homography *quality*, not inlier count alone. A transform can have 400
        # inliers and still be wrong if they all sit in one corner, and it can
        # have 40 spread evenly and be exactly right.
        t.confidence = _confidence(inliers, cfg.inliers_ok, reproj,
                                   cfg.ransac_reproj_px, overlap_fraction)

        if inliers < cfg.inliers_ok:
            t.status = DEGRADED
            t.note(f"Only {inliers} points agreed on the alignment. That is enough to "
                   f"continue, but treat what follows with caution — a weak alignment "
                   f"makes unchanged detail look changed.")
        else:
            t.note(f"Found {inliers} matching points that all agree on the same "
                   f"alignment, out of {len(good)} candidate matches.")

        t.note(f"Those points land an average of {reproj:.2f} pixels from where the "
               f"alignment predicts, on a {cfg.ransac_reproj_px:.0f}-pixel tolerance.")
        t.note(f"The reference had to be resized {scale:.2f}x and rotated "
               f"{rotation:+.1f}° to sit on top of the marketplace image.")
        t.note(f"The two overlap across {overlap_fraction * 100:.0f}% of the frame. "
               f"Only that shared area is compared.")
        t.note("The checkerboard artefact alternates squares from each image. If the "
               "artwork lines up across the square edges, the alignment is good.")
        return t


# --------------------------------------------------------------------------


def _detect(ref_gray, mkt_gray, cfg):
    """SIFT first, a binary detector second.

    The spec calls for AKAZE as the fallback. OpenCV 5's Python bindings do not
    ship AKAZE, so ORB fills the same role: a fast binary-descriptor detector
    that finds corners where SIFT's blob response starves — which is what happens
    on flat, high-contrast packaging with little texture.
    """
    sift = cv2.SIFT_create(nfeatures=cfg.max_features)
    kp_ref, des_ref = sift.detectAndCompute(ref_gray, None)
    kp_mkt, des_mkt = sift.detectAndCompute(mkt_gray, None)

    if (len(kp_ref) >= cfg.min_sift_keypoints
            and len(kp_mkt) >= cfg.min_sift_keypoints):
        return "SIFT", kp_ref, des_ref, kp_mkt, des_mkt

    orb = cv2.ORB_create(nfeatures=cfg.max_features)
    okp_ref, odes_ref = orb.detectAndCompute(ref_gray, None)
    okp_mkt, odes_mkt = orb.detectAndCompute(mkt_gray, None)
    if min(len(okp_ref), len(okp_mkt)) > min(len(kp_ref), len(kp_mkt)):
        return "ORB", okp_ref, odes_ref, okp_mkt, odes_mkt
    return "SIFT", kp_ref, des_ref, kp_mkt, des_mkt


def _reprojection_error(H, src, dst, mask) -> float:
    idx = mask.ravel().astype(bool)
    if not idx.any():
        return float("inf")
    projected = cv2.perspectiveTransform(src[idx], H)
    return float(np.linalg.norm(projected - dst[idx], axis=2).mean())


def _implied_transform(H) -> tuple[float, float]:
    """Scale and rotation implied by the homography's affine part.

    `sqrt(|det|)` of the 2x2 block is the isotropic scale factor; the angle of
    its first column is the rotation. Both are sanity checks rather than
    measurements — a nonsense match usually announces itself here first.
    """
    a = H[:2, :2] / (H[2, 2] if H[2, 2] != 0 else 1.0)
    det = float(np.linalg.det(a))
    scale = float(np.sqrt(abs(det))) if det != 0 else 0.0
    rotation = float(np.degrees(np.arctan2(a[1, 0], a[0, 0])))
    return scale, rotation


def _confidence(inliers: int, inliers_ok: int, reproj: float,
                reproj_tol: float, overlap: float) -> float:
    """Three independent ways the alignment can be bad, multiplied together.

    Multiplied rather than averaged: an alignment that is excellent on two counts
    and catastrophic on the third is not two-thirds good, it is unusable.
    """
    count_term = min(1.0, inliers / float(max(1, inliers_ok * 2)))
    error_term = max(0.0, 1.0 - (reproj / max(reproj_tol, 1e-6)))
    overlap_term = min(1.0, overlap / 0.8)
    return float(round(max(0.0, min(1.0, count_term * error_term * overlap_term)), 4))


def _refuse(ctx: PairContext, t: StageTrace, why: str) -> StageTrace:
    """Stop the pipeline, with an explanation a non-engineer can act on."""
    t.status = FAILED
    t.confidence = 0.0
    t.note(why)
    t.note("Refusing to compare is a designed outcome here, not a crash. A wrong "
           "answer is more expensive than no answer.")
    ctx.halt(CANNOT_COMPARE, "The images could not be lined up, so nothing after this "
                             "step could run.")
    return t


def _draw_matches(ref, mkt, kp_ref, kp_mkt, good, inlier_mask) -> np.ndarray:
    """Inlier correspondences only.

    Drawing all the ratio-test survivors produces a hairball that looks like
    evidence and is not; the inliers are the points the transform actually rests
    on, and a reader should see exactly those.
    """
    mask = inlier_mask.ravel().astype(bool)
    inliers = [m for m, keep in zip(good, mask) if keep]
    # Cap what is drawn: 400 lines is already an unreadable mesh, and the count
    # is reported as a metric anyway.
    step = max(1, len(inliers) // 120)
    shown = inliers[::step]
    out = cv2.drawMatches(
        ref, kp_ref, mkt, kp_mkt, shown, None,
        matchColor=(80, 200, 120), singlePointColor=(200, 200, 200),
        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
    return out


def _checkerboard(warped, mkt, valid, squares: int = 12) -> np.ndarray:
    """Alternating squares from each image.

    The single most persuasive artefact in the system: if the artwork runs
    continuously across a square boundary the alignment is right, and if it steps
    it is not. No number communicates that as directly.
    """
    h, w = mkt.shape[:2]
    size = max(16, int(round(max(h, w) / squares)))
    ys = (np.arange(h) // size)[:, None]
    xs = (np.arange(w) // size)[None, :]
    take_ref = ((ys + xs) % 2 == 0)

    out = mkt.copy()
    m = take_ref & (valid > 0)
    out[m] = warped[m]

    # A hairline grid, so the reader can see where the seams they are checking
    # actually are.
    grid = out.copy()
    for y in range(size, h, size):
        grid[y:y + 1, :] = (255, 255, 255)
    for x in range(size, w, size):
        grid[:, x:x + 1] = (255, 255, 255)
    return cv2.addWeighted(out, 0.85, grid, 0.15, 0)


register("registration")(RegistrationStage)
