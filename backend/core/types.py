"""The vocabulary the engine speaks.

Deliberately free of any domain: there is no artwork, SKU or version here, only
candidates and the evidence for choosing between them. Anything a domain needs to
carry travels in `meta`, which the engine never inspects.

The question this models is not "how alike are these two images?" but "**which**
known image is this a copy of?" — a closed set with exactly one right answer, which
is why ranking candidates against each other beats testing any of them against an
absolute bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class Candidate:
    """One known image the probe might be a copy of."""

    id: str
    content_hash: str
    image_path: Path
    # Stable tie-break rank. Ranking must be reproducible when two candidates score
    # exactly alike, and sorting on `id` would order "10" before "9". The domain
    # supplies a genuine ordering (a row id, a sequence number) instead.
    order: int = 0
    # Domain payload — version labels, approval dates, whatever. Never read here.
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Discriminator:
    """A box known to differ between two candidates.

    These are what make near-identical candidates separable. Two versions differing
    by one number are ~99.9% identical globally, which is below the noise floor of
    JPEG compression — a whole-image comparison genuinely cannot separate them, so
    the comparison has to be restricted to the places they are known to differ.
    """

    from_id: str
    to_id: str
    box: Box
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateSet:
    """The closed set of candidates for one probe, plus what separates them."""

    key: str
    candidates: tuple[Candidate, ...]
    discriminators: tuple[Discriminator, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ValueError(f"candidate set {self.key!r} is empty")

    def by_id(self) -> dict[str, Candidate]:
        return {c.id: c for c in self.candidates}

    def hash_groups(self) -> dict[str, tuple[Candidate, ...]]:
        """Candidates grouped by content hash.

        Byte-identical candidates cannot be told apart by any amount of pixel
        evidence, so ranking them against each other can only produce a tie — and a
        tie reads as "nothing explains this image", which is exactly backwards:
        every member of the group explains it equally well.
        """
        groups: dict[str, list[Candidate]] = {}
        for c in self.candidates:
            groups.setdefault(c.content_hash, []).append(c)
        return {h: tuple(sorted(g, key=lambda c: c.order))
                for h, g in groups.items()}

    def representatives(self) -> tuple[Candidate, ...]:
        """One candidate per distinct content hash, in stable order."""
        reps = [g[0] for g in self.hash_groups().values()]
        return tuple(sorted(reps, key=lambda c: c.order))

    def discriminators_between(self, a_id: str, b_id: str) -> tuple[Discriminator, ...]:
        return tuple(d for d in self.discriminators
                     if (d.from_id, d.to_id) in ((a_id, b_id), (b_id, a_id)))


@dataclass(frozen=True)
class Probe:
    """The unknown image being identified."""

    path: Path
    content_hash: str
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StageOutcome:
    """What one stage concluded.

    `decisive` is the whole control flow. A stage that returns a non-decisive
    outcome has contributed evidence but not an answer, and the engine moves on.
    Nothing can be accepted by falling off the end of the chain — that is precisely
    the failure the old procedural version had.
    """

    method: str
    matched: Candidate | None = None
    confidence: float = 0.0
    evidence: Mapping[str, Any] = field(default_factory=dict)
    decisive: bool = False

    @classmethod
    def answer(cls, method: str, matched: Candidate, confidence: float,
               **evidence: Any) -> "StageOutcome":
        return cls(method=method, matched=matched, confidence=confidence,
                   evidence=evidence, decisive=True)

    @classmethod
    def declined(cls, method: str, **evidence: Any) -> "StageOutcome":
        """Evidence gathered, no answer. The engine continues to the next stage."""
        return cls(method=method, evidence=evidence, decisive=False)


@dataclass(frozen=True)
class StageRecord:
    """One stage's contribution, kept whether or not it decided anything."""

    stage: str
    decisive: bool
    matched_id: str | None
    confidence: float
    evidence: Mapping[str, Any]
    duration_ms: float


@dataclass(frozen=True)
class MatchResult:
    """The engine's answer, with the reasoning that produced it.

    `matched is None` means the engine refused. That is a real answer, not a
    failure: where the evidence is barely better than a coin toss, refusing costs a
    reviewer one look, while guessing wrong costs the tool its credibility.
    """

    matched: Candidate | None
    method: str
    confidence: float
    trace: tuple[StageRecord, ...] = ()
    error: str | None = None

    @property
    def identified(self) -> bool:
        return self.matched is not None

    def evidence_for(self, stage: str) -> Mapping[str, Any] | None:
        for rec in self.trace:
            if rec.stage == stage:
                return rec.evidence
        return None
