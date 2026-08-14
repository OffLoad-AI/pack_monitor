"""The stage interface and registry.

A stage is a component that looks at a `MatchContext` and either answers or
declines. Stages are ordered cheapest-first and each one runs only if the ones
before it could not answer — the expensive stages exist to handle what the cheap
ones cannot, not to second-guess them.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from ..context import MatchContext
from ..types import StageOutcome


@runtime_checkable
class Stage(Protocol):
    """One step in an identification pipeline."""

    name: str

    def applicable(self, ctx: MatchContext) -> bool:
        """Whether this stage can say anything about this probe at all."""
        ...

    def run(self, ctx: MatchContext) -> StageOutcome:
        """Answer, or decline and let the next stage try."""
        ...


_REGISTRY: dict[str, Callable[..., Stage]] = {}


def register(name: str) -> Callable[[Callable[..., Stage]], Callable[..., Stage]]:
    """Register a stage factory so pipelines can be composed by name.

    Lets a deployment describe its pipeline as configuration — or a different
    problem reuse three of these stages and substitute the fourth — without the
    engine knowing what stages exist.
    """

    def deco(factory: Callable[..., Stage]) -> Callable[..., Stage]:
        if name in _REGISTRY:
            raise ValueError(f"stage {name!r} is already registered")
        _REGISTRY[name] = factory
        return factory

    return deco


def build(name: str, **kwargs) -> Stage:
    if name not in _REGISTRY:
        raise KeyError(f"unknown stage {name!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name](**kwargs)


def registered() -> list[str]:
    return sorted(_REGISTRY)


def margin_confidence(best: float, runner_up: float) -> float:
    """Confidence as the margin over the runner-up, clamped to 0..1.

    Not a probability. It answers "how much better was the winner than the next
    best?", which is the only thing a closed candidate set can honestly report.
    """
    if runner_up <= 0:
        return 1.0 if best <= 0 else 0.5
    return float(max(0.0, min(1.0, 1.0 - (best / runner_up))))
