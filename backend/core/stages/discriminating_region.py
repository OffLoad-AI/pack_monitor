"""Stage 4 — discriminating-region ranking.

The stage that does the real work. Candidates that are globally indistinguishable
are compared only inside the boxes known to differ between them, and are ranked
**against each other** rather than against an absolute bar.

That relative comparison is the single most important idea here. Every candidate
carries the same compression noise in the same boxes, so the noise is a common term
that cancels when they are compared with one another. An absolute cutoff would
instead have to straddle the noise floor of the worst image in the population —
which varies about fivefold — and would then reject good matches on hard images
while accepting bad ones on easy images. That is structural, not a tuning problem.

The candidate that looks *least changed* inside the boxes known to differ is the one
being served. If it does not beat the runner-up by the required margin, the stage
declines and the engine refuses: near a tie the ranking is barely better than a coin
toss, and an image that is not a copy of anything scores alike against every
candidate and lands here by design.
"""

from __future__ import annotations

from ..context import MatchContext
from ..imaging.metrics import region_signal
from ..imaging.regions import scale_box
from ..types import StageOutcome
from .base import margin_confidence, register

METHOD = "REGION_CHECK"


class DiscriminatingRegionStage:
    name = "discriminating_region"

    def applicable(self, ctx: MatchContext) -> bool:
        return bool(ctx.candidates.discriminators) and len(self._pool(ctx)) > 1

    @staticmethod
    def _pool(ctx: MatchContext) -> tuple:
        """The candidates worth ranking.

        If the whole-image screen narrowed the field to several clean candidates,
        rank those; otherwise rank everything. Fractions are memoized, so consulting
        them again here costs nothing and keeps this stage independent of what ran
        before it.
        """
        ranked = ctx.ranked_by_fraction()
        cutoff = ctx.config.whole_image.clean_fraction
        clean = [c for c, f in ranked if f < cutoff]
        if len(clean) > 1:
            return tuple(clean)
        return tuple(c for c, _ in ranked)

    def run(self, ctx: MatchContext) -> StageOutcome:
        pool = self._pool(ctx)
        cfg = ctx.config.region

        totals: list[tuple[float, int, str]] = []
        per_candidate: dict[str, float] = {}
        for candidate in pool:
            score = ctx.score(candidate)
            scale = ctx.scale(candidate)
            bounds = ctx.working_shape(candidate)
            total = 0.0
            for disc in ctx.candidates.discriminators:
                box = scale_box(disc.box, scale, bounds)
                total += region_signal(score, box, cfg.signal_cap,
                                       cfg.signal_top_fraction)
            totals.append((total, candidate.order, candidate.id))
            per_candidate[candidate.id] = total

        # Lowest total wins: looking unchanged where the candidates are known to
        # differ is what identifies the one being served.
        totals.sort()
        best_total, _order, best_id = totals[0]
        runner_up = totals[1][0] if len(totals) > 1 else float("inf")

        evidence = {
            "margin_ratio": cfg.margin_ratio,
            "totals": {cid: round(t, 8) for cid, t in per_candidate.items()},
            "best_id": best_id,
            "best_total": round(best_total, 8),
            "runner_up_total": (round(runner_up, 8)
                                if runner_up != float("inf") else None),
            "regions_considered": len(ctx.candidates.discriminators),
        }

        if best_total * cfg.margin_ratio <= runner_up:
            matched = ctx.candidates.by_id()[best_id]
            return StageOutcome.answer(
                METHOD, matched, margin_confidence(best_total, runner_up),
                **evidence)

        return StageOutcome.declined(METHOD, refused_on="margin", **evidence)


@register("discriminating_region")
def _factory() -> DiscriminatingRegionStage:
    return DiscriminatingRegionStage()
