"""Photograph fallback track — interface only, deliberately not implemented (§4).

When a third-party seller photographs the pack themselves, the listing image no
longer originates from the brand's artwork file. Hash matching cannot help, and
pixel differencing is meaningless because there is a camera, a perspective, and a
lighting setup between the two images. That case needs a genuinely different
method: keypoint detection, a homography to rectify the pack face, then a
structural comparison of the rectified crop.

The MVP routes those images to `UNKNOWN_IMAGE` rather than guessing. The
quality/size combinations where the primary track fails are reported in RESULTS.md,
because they are what defines this module's eventual scope.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class FallbackResult:
    matched_version_id: int | None
    confidence: float
    match_method: str
    regions: list[dict]


def identify_photographed_pack(
    scraped_rgb: np.ndarray,
    candidates: list[dict],
    cfg: dict,
) -> FallbackResult:
    """Identify which artwork version a photographed pack is showing.

    TODO: implement the photograph track.
      1. SIFT/AKAZE keypoints on the scraped image and each candidate reference.
      2. Ratio-test matching, then RANSAC to a homography — reject if the inlier
         count or the homography's condition number is poor.
      3. Warp the reference into the scraped frame, mask to the overlap.
      4. Compare with SSIM over local windows rather than absolute pixel diff;
         illumination and white balance make absolute differences useless here.
      5. Confidence must reflect the homography quality, not just the SSIM score.

    Until then this returns UNKNOWN_IMAGE, which is the honest answer: the primary
    track cannot identify the image and nothing else has looked at it.
    """
    return FallbackResult(
        matched_version_id=None,
        confidence=0.0,
        match_method="NONE",
        regions=[],
    )
