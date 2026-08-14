"""Evaluating an engine against labelled cases.

Domain-agnostic, so any "which known image is this?" problem can be measured the
same way: supply probes with expected answers and get accuracy back, broken down
by whatever facets you attached.

The one opinion it holds is that **refusals and wrong answers are different
failures and must never be pooled into one error rate**. A refusal costs a reviewer
one look. A confident wrong answer costs the tool its credibility. A single "error"
number hides exactly the distinction you need to act on.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .engine import Engine
from .types import CandidateSet, Probe

CORRECT = "correct"
WRONG = "wrong"
REFUSED = "refused"
CORRECTLY_REFUSED = "correctly_refused"
ERRORED = "errored"


@dataclass(frozen=True)
class EvaluationCase:
    """One labelled probe.

    `expected_id` of `None` means the engine *should* refuse — a probe that is not
    a copy of anything in the set. Those cases are as important as the positive
    ones: an identifier that never refuses is not trustworthy, it is just eager.
    """

    probe: Probe
    candidates: CandidateSet
    expected_id: str | None = None
    facets: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class Report:
    total: int = 0
    outcomes: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    by_facet: dict[str, dict[Any, dict[str, int]]] = field(default_factory=dict)
    failures: list[dict] = field(default_factory=list)

    def count(self, outcome: str) -> int:
        # Always via .get: the tallies are frozen to a plain dict before returning,
        # so a category nothing landed in is simply absent.
        return self.outcomes.get(outcome, 0)

    @property
    def decided(self) -> int:
        """Cases where the engine committed to an answer."""
        return self.count(CORRECT) + self.count(WRONG)

    @property
    def accuracy_when_decided(self) -> float:
        """Accuracy over the cases it accepted — the number that matters.

        Reported separately from coverage because refusing is a valid answer, and
        averaging the two populations together describes neither.
        """
        return self.count(CORRECT) / self.decided if self.decided else 0.0

    @property
    def coverage(self) -> float:
        """Share of cases the engine was willing to answer at all."""
        return self.decided / self.total if self.total else 0.0

    def facet_table(self, name: str) -> list[tuple[Any, int, int, float]]:
        """`(value, correct, decided, accuracy)` rows for one facet, sorted."""
        rows = []
        for value, counts in sorted(self.by_facet.get(name, {}).items(),
                                    key=lambda kv: str(kv[0])):
            correct = counts.get(CORRECT, 0)
            decided = correct + counts.get(WRONG, 0)
            rows.append((value, correct, decided,
                         correct / decided if decided else 0.0))
        return rows

    def summary(self) -> str:
        lines = [
            f"cases               {self.total}",
            f"correct             {self.count(CORRECT)}",
            f"wrong               {self.count(WRONG)}",
            f"refused             {self.count(REFUSED)}",
            f"correctly refused   {self.count(CORRECTLY_REFUSED)}",
            f"errored             {self.count(ERRORED)}",
            f"accuracy (decided)  {self.accuracy_when_decided:.4%}",
            f"coverage            {self.coverage:.4%}",
        ]
        return "\n".join(lines)


def _equivalent(cset: CandidateSet, a_id: str, b_id: str) -> bool:
    """Whether two candidate ids are indistinguishable by any pixel evidence.

    Byte-identical candidates under different labels are the same image, so an
    answer of either is correct. Scoring them as a miss would penalise the engine
    for a distinction that does not exist.
    """
    if a_id == b_id:
        return True
    by_id = cset.by_id()
    if a_id not in by_id or b_id not in by_id:
        return False
    return by_id[a_id].content_hash == by_id[b_id].content_hash


def classify(cset: CandidateSet, expected_id: str | None,
             matched_id: str | None, errored: bool = False) -> str:
    if errored:
        return ERRORED
    if expected_id is None:
        return CORRECTLY_REFUSED if matched_id is None else WRONG
    if matched_id is None:
        return REFUSED
    return CORRECT if _equivalent(cset, expected_id, matched_id) else WRONG


def evaluate(engine: Engine, cases: Iterable[EvaluationCase],
             facets: Sequence[str] = (),
             keep_failures: int = 50) -> Report:
    """Run every case and tally the outcomes."""
    report = Report()
    for name in facets:
        report.by_facet[name] = defaultdict(lambda: defaultdict(int))

    for case in cases:
        result = engine.identify(case.probe, case.candidates)
        matched_id = result.matched.id if result.matched else None
        outcome = classify(case.candidates, case.expected_id, matched_id,
                           errored=result.error is not None)

        report.total += 1
        report.outcomes[outcome] += 1
        for name in facets:
            report.by_facet[name][case.facets.get(name)][outcome] += 1

        if outcome in (WRONG, ERRORED) and len(report.failures) < keep_failures:
            report.failures.append({
                "probe": str(case.probe.path),
                "candidate_set": case.candidates.key,
                "expected": case.expected_id,
                "matched": matched_id,
                "method": result.method,
                "confidence": round(result.confidence, 4),
                "outcome": outcome,
                "error": result.error,
                "facets": dict(case.facets),
            })

    # defaultdicts make later mutation silent; freeze before returning.
    report.outcomes = dict(report.outcomes)
    report.by_facet = {k: {kk: dict(vv) for kk, vv in v.items()}
                       for k, v in report.by_facet.items()}
    return report
