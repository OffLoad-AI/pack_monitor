"""Stage 1 — byte-identical match.

If the probe's bytes are identical to a candidate's, that *is* the candidate. It
is never scored, ranked, weighted or checked against anything else, because there
is nothing a pixel comparison could add to proof.
"""

from __future__ import annotations

from ..context import MatchContext
from ..types import StageOutcome
from .base import register

METHOD = "HASH_EXACT"


class HashExactStage:
    name = "hash_exact"

    def applicable(self, ctx: MatchContext) -> bool:
        return bool(ctx.probe.content_hash)

    def run(self, ctx: MatchContext) -> StageOutcome:
        for candidate in ctx.candidates.candidates:
            if candidate.content_hash == ctx.probe.content_hash:
                return StageOutcome.answer(
                    METHOD, candidate, 1.0,
                    content_hash=ctx.probe.content_hash)
        return StageOutcome.declined(METHOD, content_hash=ctx.probe.content_hash)


@register("hash_exact")
def _factory() -> HashExactStage:
    return HashExactStage()
