"""Stage 3 — whole-image screening.

Cheap, and answers only the easy cases. It fires where candidates differ grossly —
a palette shift, a redesigned pack — and resolves a small minority of a typical
run. That is the premise confirmed rather than a shortfall: candidates differing by
one number are ~99.9% identical globally, and no whole-image statistic can separate
them.

A candidate is "clean" if it differs from the probe by no more than compression
noise. Exactly one clean candidate is an answer. Several means the screen cannot
choose, and none means it cannot either — both defer to the region stage.
"""

from __future__ import annotations

from ..context import MatchContext
from ..types import StageOutcome
from .base import margin_confidence, register

METHOD = "PIXEL_DIFF"


class WholeImageStage:
    name = "whole_image"

    def applicable(self, ctx: MatchContext) -> bool:
        return True

    def run(self, ctx: MatchContext) -> StageOutcome:
        ranked = ctx.ranked_by_fraction()
        cutoff = ctx.config.whole_image.clean_fraction
        clean = [(c, f) for c, f in ranked if f < cutoff]

        evidence = {
            "clean_fraction_cutoff": cutoff,
            "fractions": {c.id: round(f, 8) for c, f in ranked},
            "clean_ids": [c.id for c, _ in clean],
        }

        if len(clean) == 1:
            best, best_fraction = clean[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else 1.0
            return StageOutcome.answer(
                METHOD, best, margin_confidence(best_fraction, runner_up),
                **evidence)

        return StageOutcome.declined(METHOD, **evidence)


@register("whole_image")
def _factory() -> WholeImageStage:
    return WholeImageStage()
