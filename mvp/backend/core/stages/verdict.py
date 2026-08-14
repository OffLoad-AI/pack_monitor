"""Stage 6 — verdict.

Reduces the region list to one answer. The rules are a table, deliberately, so
that reading the code and reading the specification are the same activity.

`CANNOT_COMPARE` and `NEEDS_REVIEW` are **designed outcomes, not failures**, and
the UI presents them that way. This carries over the discipline that governs the
version-identification build: there are two ways to be wrong and they cost wildly
different amounts. Reporting good artwork as changed sends someone to investigate
a non-problem, and a few of those and the team stops trusting the tool. Declining
costs one person one look. So the pipeline declines.

This stage always runs, even when an earlier stage halted the pipeline, because a
halt *is* a verdict and a comparison with no verdict row would be a gap in the
record.
"""

from __future__ import annotations

import numpy as np

from ..trace import OK, StageTrace
from ..types import (
    CANNOT_COMPARE,
    COSMETIC,
    DIFFERENT,
    IDENTICAL,
    MATCH,
    MATCH_WITH_COSMETIC_DIFFERENCES,
    MATERIAL,
    NEEDS_REVIEW,
    NO_DIFFERENCE,
    NONE,
    PairContext,
    UNCERTAIN,
)
from .base import register

# What each verdict means, in the words the UI shows. Defined next to the rule
# that produces it so the two cannot drift apart.
EXPLANATION = {
    IDENTICAL: "The two files are byte-for-byte the same file.",
    MATCH: "The artwork is the same. Nothing beyond re-encoding separates these "
           "two images.",
    MATCH_WITH_COSMETIC_DIFFERENCES:
        "The artwork says the same thing. What differs is how it is written or "
        "coloured, not what it claims.",
    DIFFERENT: "The marketplace image shows different artwork. At least one change "
               "alters what the pack says.",
    NEEDS_REVIEW: "Something differs, but not in a way this tool can settle on its "
                  "own. A person needs to look.",
    CANNOT_COMPARE: "These two images could not be lined up well enough to compare.",
}


class VerdictStage:
    name = "verdict"

    def applicable(self, ctx: PairContext) -> bool:
        return True

    def run(self, ctx: PairContext) -> StageTrace:
        t = StageTrace(stage=self.name, status=OK)

        material = [r for r in ctx.regions if r.severity == MATERIAL]
        uncertain = [r for r in ctx.regions if r.severity == UNCERTAIN]
        cosmetic = [r for r in ctx.regions if r.severity == COSMETIC]
        inert = [r for r in ctx.regions if r.severity == NONE]

        verdict, confidence = self._decide(ctx, material, uncertain, cosmetic)
        ctx.verdict = verdict
        ctx.confidence = confidence

        t.confidence = confidence
        t.metric(verdict=verdict,
                 regions_total=len(ctx.regions),
                 regions_material=len(material),
                 regions_uncertain=len(uncertain),
                 regions_cosmetic=len(cosmetic),
                 regions_no_difference=len(inert),
                 halted_at=ctx.halt_verdict)

        t.note(EXPLANATION[verdict])

        if verdict == DIFFERENT:
            for r in material[:5]:
                t.note(r.detail)
            if len(material) > 5:
                t.note(f"...and {len(material) - 5} more material change(s).")
        elif verdict == NEEDS_REVIEW:
            for r in uncertain[:5]:
                t.note(r.detail)
            if len(uncertain) > 5:
                t.note(f"...and {len(uncertain) - 5} more region(s) needing review.")
            t.note("Declining to guess here is deliberate. A wrong 'these differ' "
                   "costs more than an honest 'I am not sure'.")
        elif verdict == MATCH_WITH_COSMETIC_DIFFERENCES:
            for r in cosmetic[:5]:
                t.note(r.detail)
        elif verdict == CANNOT_COMPARE:
            t.note("Not enough matching detail was found to line the two images up. "
                   "This usually means they show different products, or one is too "
                   "low-resolution.")

        if inert and verdict in (MATCH, MATCH_WITH_COSMETIC_DIFFERENCES):
            t.note(f"{len(inert)} region(s) looked different but read the same, which "
                   f"is what compression and print variation look like.")

        return t

    # -- the table ---------------------------------------------------------

    def _decide(self, ctx: PairContext, material, uncertain, cosmetic
                ) -> tuple[str, float]:
        # An earlier stage already answered. Hash equality is proof and does not
        # get re-derived; a registration failure cannot be argued with.
        if ctx.halt_verdict == IDENTICAL:
            return IDENTICAL, 1.0
        if ctx.halt_verdict == CANNOT_COMPARE:
            return CANNOT_COMPARE, 0.0
        if ctx.halt_verdict == MATCH:
            return MATCH, self._pipeline_confidence(ctx)

        if material:
            return DIFFERENT, self._pipeline_confidence(ctx)
        if uncertain:
            return NEEDS_REVIEW, self._pipeline_confidence(ctx)
        if cosmetic:
            return MATCH_WITH_COSMETIC_DIFFERENCES, self._pipeline_confidence(ctx)
        return MATCH, self._pipeline_confidence(ctx)

    def _pipeline_confidence(self, ctx: PairContext) -> float:
        """The weakest link, not the average.

        A comparison whose registration was excellent and whose OCR was
        unreadable is not "fairly confident" — it is as confident as the OCR was.
        Averaging would let a strong stage launder a weak one.
        """
        scores = [tr.confidence for tr in ctx.recorder.traces
                  if tr.confidence is not None and tr.stage != "hash"]
        if not scores:
            return 0.0
        return float(round(np.min(scores), 4))


register("verdict")(VerdictStage)
