"""The engine reused on a problem that is not packaging compliance.

The point of a domain-agnostic core is that pointing it at a different question
means supplying candidates and labelled probes — no core changes, no new stage.
Here the "candidates" are scanned form templates and the question is which revision
of a form a scan is a copy of. Nothing in `core` knows the difference.

This doubles as the reusability regression test: if someone leaks packaging
concepts into the engine, this file stops compiling.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from core.config import EngineConfig
from core.engine import Engine
from core.harness import (
    CORRECT,
    CORRECTLY_REFUSED,
    REFUSED,
    WRONG,
    EvaluationCase,
    evaluate,
)
from core.imaging.loader import sha256_file
from core.types import Candidate, CandidateSet, Discriminator, Probe

SIZE = 200


def _form(revision: int) -> np.ndarray:
    """A 'scanned form' — shared layout, one differing field box.

    The alternating edge band matters and is not decoration. De-padding strips
    uniform bands inward, so a page with quiet margins gets cropped when it arrives
    as a scan and not cropped as a stored template, leaving the two on different
    grids. Real documents have edge-to-edge content, registration marks or a
    printed border that serve the same purpose — the packaging equivalent is a
    full-bleed trim tick.
    """
    img = np.full((SIZE, SIZE, 3), 235, dtype=np.uint8)
    img[::5, :] = 120                      # ruled lines
    img[10:30, 10:190] = 40                # header bar
    img[150:170, 20:60] = 80               # signature block
    # The field that changes between revisions.
    img[80:100, 60:120] = (revision * 60) % 256

    edge = 6
    for i in range(0, SIZE, 20):
        shade = 30 if (i // 20) % 2 == 0 else 200
        img[:edge, i:i + 20] = shade
        img[-edge:, i:i + 20] = shade
        img[i:i + 20, :edge] = shade
        img[i:i + 20, -edge:] = shade
    return img


def _save(path, arr) -> str:
    Image.fromarray(arr).save(path)
    return str(path)


def _candidate(cid, path, order) -> Candidate:
    from pathlib import Path

    return Candidate(id=cid, content_hash=sha256_file(path),
                     image_path=Path(path), order=order)


@pytest.fixture
def form_set(tmp_path):
    """Three revisions of one form, plus the box that separates them."""
    paths = [_save(tmp_path / f"rev{i}.png", _form(i)) for i in (1, 2, 3)]
    candidates = tuple(_candidate(f"rev{i}", p, i)
                       for i, p in zip((1, 2, 3), paths))
    field_box = (60, 80, 60, 20)
    discs = (Discriminator("rev1", "rev2", field_box),
             Discriminator("rev2", "rev3", field_box))
    return CandidateSet("form-A", candidates, discs), paths


def test_engine_identifies_a_non_packaging_candidate_set(tmp_path, form_set):
    cset, paths = form_set
    engine = Engine(config=EngineConfig())

    # A faithful copy of revision 2, re-encoded as JPEG like a real scan pipeline.
    scan = tmp_path / "scan.jpg"
    Image.fromarray(_form(2)).save(scan, quality=80)

    result = engine.identify(
        Probe(path=scan, content_hash=sha256_file(scan)), cset)

    assert result.matched is not None
    assert result.matched.id == "rev2"


def test_harness_scores_and_separates_refusals_from_wrong_answers(
        tmp_path, form_set):
    cset, _paths = form_set
    engine = Engine(config=EngineConfig())

    cases = []
    for rev in (1, 2, 3):
        for quality in (95, 70):
            p = tmp_path / f"scan_r{rev}_q{quality}.jpg"
            Image.fromarray(_form(rev)).save(p, quality=quality)
            cases.append(EvaluationCase(
                probe=Probe(path=p, content_hash=sha256_file(p)),
                candidates=cset,
                expected_id=f"rev{rev}",
                facets={"quality": quality},
            ))

    # A page that is not this form at all: the engine should refuse it.
    rng = np.random.default_rng(7)
    foreign = tmp_path / "foreign.png"
    _save(foreign, rng.integers(0, 255, (SIZE, SIZE, 3), dtype=np.uint8))
    cases.append(EvaluationCase(
        probe=Probe(path=foreign, content_hash=sha256_file(foreign)),
        candidates=cset, expected_id=None, facets={"quality": None}))

    report = evaluate(engine, cases, facets=("quality",))

    assert report.total == 7
    assert report.outcomes.get(WRONG, 0) == 0, report.failures
    assert report.outcomes.get(CORRECT, 0) == 6
    assert report.outcomes.get(CORRECTLY_REFUSED, 0) == 1
    assert report.accuracy_when_decided == 1.0

    # Facet breakdown is available for any key the caller attached.
    rows = dict((value, acc) for value, _c, _d, acc in
                report.facet_table("quality"))
    assert rows[95] == 1.0
    assert rows[70] == 1.0


def test_harness_counts_a_refusal_separately_from_a_wrong_answer():
    """Pooling the two into one error rate hides the only operational difference."""
    from core.harness import classify

    cset = CandidateSet("s", (Candidate("a", "h1", "a.png", 1),
                              Candidate("b", "h2", "b.png", 2)))

    assert classify(cset, "a", "a") == CORRECT
    assert classify(cset, "a", "b") == WRONG
    assert classify(cset, "a", None) == REFUSED
    assert classify(cset, None, None) == CORRECTLY_REFUSED
    assert classify(cset, None, "a") == WRONG


def test_byte_identical_candidates_are_scored_as_equivalent():
    """Two labels over identical bytes are one image; answering either is right."""
    from core.harness import classify

    cset = CandidateSet("s", (Candidate("a", "same", "a.png", 1),
                              Candidate("b", "same", "b.png", 2)))

    assert classify(cset, "a", "b") == CORRECT
