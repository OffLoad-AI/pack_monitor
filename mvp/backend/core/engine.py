"""The comparison engine.

Runs an ordered list of stages over one pair. Two properties are load-bearing:

**Every stage emits a trace, including on the failure path.** A stage that raises
gets a `FAILED` trace carrying the exception, and stages after a halt get a
`SKIPPED` trace saying why they were skipped. There is no path through this
function that produces a comparison with a missing stage row, because the entire
purpose of the build is to show the method working or not working, and a gap in
the trace is indistinguishable from a lie.

**Refusal is the default.** `CANNOT_COMPARE` is what happens when nothing
establishes otherwise; a positive verdict requires the verdict stage to say so.
That is the guarantee the other build's procedural version lacked, and the reason
it once returned PASS for random noise.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

from .config import EngineConfig
from .stages.base import Stage
from .trace import FAILED, TraceRecorder
from .types import CANNOT_COMPARE, ComparisonResult, PairContext


def default_stages() -> list[Stage]:
    """The pipeline, in order. Each stage's output is the next one's input.

    Unlike the other build's cheapest-first chain, this is a genuine sequence:
    registration cannot run before normalization and the structural diff is
    meaningless before registration. The one early exit is the hash — when it
    fires it is proof, and everything after it is redundant.
    """
    from .stages.hash_exact import HashStage
    from .stages.load_normalize import LoadNormalizeStage
    from .stages.region_ocr import RegionOcrStage
    from .stages.registration import RegistrationStage
    from .stages.structural_diff import StructuralDiffStage
    from .stages.text_compare import TextCompareStage
    from .stages.verdict import VerdictStage

    return [
        LoadNormalizeStage(),
        HashStage(),
        RegistrationStage(),
        StructuralDiffStage(),
        RegionOcrStage(),
        TextCompareStage(),
        VerdictStage(),
    ]


@dataclass
class Engine:
    """An ordered stage chain plus the configuration the stages read."""

    config: EngineConfig
    stages: Sequence[Stage] = ()

    def __post_init__(self) -> None:
        if not self.stages:
            self.stages = default_stages()

    def compare(self, ctx: PairContext) -> ComparisonResult:
        """Run one pair through every stage and return the verdict with its trace."""
        started = time.perf_counter()
        recorder: TraceRecorder = ctx.recorder
        error: str | None = None

        for stage in self.stages:
            # A halted pipeline still records what it did not do, and why. The
            # verdict stage is the exception: it must always run, because a halt
            # is a verdict, not an absence of one.
            if ctx.halted and stage.name != "verdict":
                recorder.skipped(stage.name, ctx.halt_reason)
                continue

            if not stage.applicable(ctx):
                recorder.skipped(stage.name,
                                 "There was nothing for this step to do on this pair.")
                continue

            trace, t0 = recorder.begin(stage.name)
            try:
                produced = stage.run(ctx)
            except Exception as exc:  # noqa: BLE001 — a bad file must still explain itself
                trace.status = FAILED
                trace.metric(error=f"{type(exc).__name__}: {exc}")
                trace.note(f"This step could not complete: {exc}")
                recorder.finish(trace, t0)
                error = f"{type(exc).__name__}: {exc}"
                ctx.halt(CANNOT_COMPARE, "An earlier step failed, so this one was skipped.")
                continue

            # A stage may return its own trace object or fill in the one it was
            # handed; both are supported so a stage can be written either way.
            final = produced if produced is not None else trace
            if final is not trace:
                final.artifacts.update(trace.artifacts)
            recorder.finish(final, t0)

        elapsed = (time.perf_counter() - started) * 1000.0
        return ComparisonResult(
            # Refuse by default: reaching here without a verdict is a refusal.
            verdict=ctx.verdict or CANNOT_COMPARE,
            confidence=ctx.confidence,
            regions=ctx.regions,
            traces=recorder.traces,
            duration_ms=elapsed,
            reference_sha256=ctx.reference_sha256 or "",
            marketplace_sha256=ctx.marketplace_sha256 or "",
            error=error,
        )
