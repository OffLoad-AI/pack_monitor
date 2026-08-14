"""Photograph track — interface only, deliberately not implemented.

When a third-party seller photographs the pack themselves, the image no longer
originates from the brand's artwork file. Hashing cannot help and pixel
differencing is meaningless, because there is a camera, a perspective and a
lighting setup between the two images. That case needs a genuinely different
method, so it gets its own stage rather than a branch inside another one.

Being a stage is the point: implementing it means filling in `run` and changing
nothing else, and a deployment that does not want it simply leaves it out of the
chain.
"""

from __future__ import annotations

from ..context import MatchContext
from ..types import StageOutcome
from .base import register

METHOD = "PHOTOGRAPH"


class PhotographFallbackStage:
    """Declines everything until the photograph track is implemented.

    TODO: implement the photograph track.
      1. SIFT/AKAZE keypoints on the probe and each candidate.
      2. Ratio-test matching, then RANSAC to a homography — reject on poor inlier
         count or a badly conditioned homography.
      3. Warp the candidate into the probe's frame, mask to the overlap.
      4. Compare with SSIM over local windows rather than absolute pixel
         difference: illumination and white balance make absolute differences
         useless once a camera is involved.
      5. Confidence must reflect homography quality, not just the SSIM score.

    Declining is the honest answer meanwhile — the primary track could not identify
    the image and nothing else has looked at it.
    """

    name = "photograph_fallback"

    def applicable(self, ctx: MatchContext) -> bool:
        return False

    def run(self, ctx: MatchContext) -> StageOutcome:
        return StageOutcome.declined(METHOD, reason="not_implemented")


@register("photograph_fallback")
def _factory() -> PhotographFallbackStage:
    return PhotographFallbackStage()
