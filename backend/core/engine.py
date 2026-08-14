"""The identification engine.

Runs an ordered list of stages over a probe and returns the first decisive answer,
along with the full reasoning whether or not anything decided. That is the entire
control flow, and its important property is what it *cannot* do: there is no path
by which a probe is accepted because the chain ran out. Refusal is what happens by
default, and accepting requires a stage to say so explicitly.

Composing a pipeline for a different problem means passing different stages. The
engine has no opinion about what they are.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

from .config import EngineConfig
from .context import ImageStore, MatchContext
from .stages.base import Stage
from .types import CandidateSet, MatchResult, Probe, StageRecord

NO_MATCH_METHOD = "NONE"


def default_stages() -> list[Stage]:
    """The standard cheapest-first chain.

    Order is load-bearing. Hashing is proof and costs nothing, so it goes first.
    Whole-image screening is cheap and settles the grossly-different cases. Region
    ranking is expensive and handles what the screen cannot. The lone-candidate rule
    goes after both because it only applies where ranking is impossible, and the
    photograph track goes last because it is for images the others cannot explain
    at all.
    """
    from .stages.discriminating_region import DiscriminatingRegionStage
    from .stages.hash_exact import HashExactStage
    from .stages.photograph_fallback import PhotographFallbackStage
    from .stages.single_candidate import SingleCandidateStage
    from .stages.whole_image import WholeImageStage

    return [
        HashExactStage(),
        WholeImageStage(),
        DiscriminatingRegionStage(),
        SingleCandidateStage(),
        PhotographFallbackStage(),
    ]


@dataclass
class Engine:
    """An ordered stage chain plus the configuration they read."""

    config: EngineConfig
    stages: Sequence[Stage] = ()

    def __post_init__(self) -> None:
        if not self.stages:
            self.stages = default_stages()

    def context(self, probe: Probe, candidates: CandidateSet,
                store: ImageStore | None = None) -> MatchContext:
        return MatchContext(probe, candidates, self.config, store)

    def identify(self, probe: Probe, candidates: CandidateSet,
                 store: ImageStore | None = None) -> MatchResult:
        """Convenience wrapper for callers that do not need the context afterwards."""
        return self.run(self.context(probe, candidates, store))

    def run(self, ctx: MatchContext) -> MatchResult:
        """Identify one probe against a closed candidate set.

        Takes the context rather than building one, so a caller that needs a
        by-product afterwards — the normalized probe, a difference map — reads it
        off the same context instead of paying to recompute it.

        Any exception from a stage is captured into the result rather than raised:
        one unreadable file must not sink a batch of fifteen thousand.
        """
        trace: list[StageRecord] = []

        for stage in self.stages:
            started = time.perf_counter()
            try:
                if not stage.applicable(ctx):
                    continue
                outcome = stage.run(ctx)
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop a run
                elapsed = (time.perf_counter() - started) * 1000.0
                trace.append(StageRecord(
                    stage=stage.name, decisive=False, matched_id=None,
                    confidence=0.0, duration_ms=elapsed,
                    evidence={"error": f"{type(exc).__name__}: {exc}"}))
                return MatchResult(
                    matched=None, method=NO_MATCH_METHOD, confidence=0.0,
                    trace=tuple(trace), error=f"{type(exc).__name__}: {exc}")

            elapsed = (time.perf_counter() - started) * 1000.0
            trace.append(StageRecord(
                stage=stage.name,
                decisive=outcome.decisive,
                matched_id=outcome.matched.id if outcome.matched else None,
                confidence=outcome.confidence,
                evidence=outcome.evidence,
                duration_ms=elapsed,
            ))

            if outcome.decisive and outcome.matched is not None:
                return MatchResult(
                    matched=outcome.matched, method=outcome.method,
                    confidence=outcome.confidence, trace=tuple(trace))

        # Every stage declined. No known image explains this probe.
        return MatchResult(matched=None, method=NO_MATCH_METHOD, confidence=0.0,
                           trace=tuple(trace))
