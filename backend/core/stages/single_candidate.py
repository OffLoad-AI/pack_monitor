"""The lone-candidate case, which needs its own rule.

When a candidate set holds exactly one distinct image there is nothing to rank
against, so every stage built on relative comparison has nothing to say. That is
not a rare corner: it is the state of every candidate set on first deployment, and
the permanent state of anything never revised.

The previous implementation accepted the only candidate here unconditionally, as a
fallthrough branch with no test attached. The consequence was that on a
single-version registry a completely different product measured a whole-image
difference of 0.96 and random noise measured 0.62, and **both were reported as a
clean match**. Refusal was unreachable in that state.

This stage requires positive evidence instead: the lone candidate has to actually
look like the probe. If it does not, it declines and the engine refuses.
"""

from __future__ import annotations

from ..context import MatchContext
from ..types import StageOutcome
from .base import margin_confidence, register

METHOD = "PIXEL_DIFF"


class SingleCandidateStage:
    name = "single_candidate"

    def applicable(self, ctx: MatchContext) -> bool:
        # Distinct images, not labels: several byte-identical candidates are one
        # image as far as any pixel evidence is concerned.
        return len(ctx.candidates.representatives()) == 1

    def run(self, ctx: MatchContext) -> StageOutcome:
        candidate = ctx.candidates.representatives()[0]
        fraction = ctx.whole_fraction(candidate)
        cutoff = ctx.config.single_candidate_threshold

        evidence = {
            "candidate_id": candidate.id,
            "fraction": round(fraction, 8),
            "accept_below": cutoff,
        }

        if fraction < cutoff:
            return StageOutcome.answer(
                METHOD, candidate, margin_confidence(fraction, 1.0), **evidence)

        # Nothing else can vouch for it and it does not resemble the one candidate
        # there is, so the honest answer is that no known image explains this probe.
        return StageOutcome.declined(
            METHOD, refused_on="lone_candidate_unlike_probe", **evidence)


@register("single_candidate")
def _factory() -> SingleCandidateStage:
    return SingleCandidateStage()
