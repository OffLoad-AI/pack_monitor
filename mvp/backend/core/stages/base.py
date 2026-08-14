"""The stage interface and registry.

The protocol is the one from the version-identification build, with one change
that follows from what this build is for: a stage returns a `StageTrace` rather
than a `StageOutcome`. There is no candidate to match, so a stage's product is
always evidence — and evidence is what the frontend renders.

This is a different stage set, not a different engine.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from ..trace import StageTrace
from ..types import PairContext


@runtime_checkable
class Stage(Protocol):
    """One step in the pair-comparison pipeline."""

    name: str

    def applicable(self, ctx: PairContext) -> bool:
        """Whether this stage has anything to do for this pair."""
        ...

    def run(self, ctx: PairContext) -> StageTrace:
        """Do the work and return the trace explaining it."""
        ...


_REGISTRY: dict[str, Callable[..., Stage]] = {}


def register(name: str) -> Callable[[Callable[..., Stage]], Callable[..., Stage]]:
    """Register a stage factory so pipelines can be composed by name."""

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
