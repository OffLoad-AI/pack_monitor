"""Stage-level unit tests.

These exercise one stage at a time against hand-built candidate sets, with no
process pool, no database and no corpus. That is the point of the stage interface:
before this, the only way to test the whole-image screen was to run a batch job and
infer what it had done from the verdicts that came out.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from core.config import EngineConfig
from core.context import DictImageStore, MatchContext
from core.engine import Engine
from core.imaging.loader import sha256_file
from core.stages.discriminating_region import DiscriminatingRegionStage
from core.stages.hash_exact import HashExactStage
from core.stages.single_candidate import SingleCandidateStage
from core.stages.whole_image import WholeImageStage
from core.types import Candidate, CandidateSet, Probe

SIZE = 240


def _textured(seed: int) -> np.ndarray:
    """A deterministic non-uniform image.

    Non-uniform on purpose: border detection strips uniform bands, and a flat
    colour field would be cropped to nothing.
    """
    rng = np.random.default_rng(seed)
    img = np.full((SIZE, SIZE, 3), 200, dtype=np.uint8)
    img[::4, :, :] = 60
    img[:, ::4, :] = 90
    img[20:60, 20:60] = rng.integers(0, 255, (40, 40, 3), dtype=np.uint8)
    return img


def _with_patch(base: np.ndarray, box, colour) -> np.ndarray:
    """`base` with one box repainted — a localized edit, like a changed digit."""
    out = base.copy()
    x, y, w, h = box
    out[y:y + h, x:x + w] = colour
    return out


def _write(path, arr: np.ndarray) -> str:
    Image.fromarray(arr).save(path)
    return str(path)


def _candidate(cid: str, path, order: int, **meta) -> Candidate:
    from pathlib import Path

    return Candidate(id=cid, content_hash=sha256_file(path),
                     image_path=Path(path), order=order, meta=meta)


@pytest.fixture
def cfg() -> EngineConfig:
    return EngineConfig()


def _ctx(probe_path, cset, cfg, images=None) -> MatchContext:
    probe = Probe(path=probe_path, content_hash=sha256_file(probe_path))
    store = DictImageStore(images) if images else None
    return MatchContext(probe, cset, cfg, store)


# --------------------------------------------------------------------------
# hash_exact
# --------------------------------------------------------------------------


def test_hash_exact_matches_identical_bytes(tmp_path, cfg):
    base = _textured(1)
    p = _write(tmp_path / "v1.png", base)
    cset = CandidateSet("P", (_candidate("1", p, 1),))

    outcome = HashExactStage().run(_ctx(p, cset, cfg))

    assert outcome.decisive
    assert outcome.matched.id == "1"
    assert outcome.confidence == 1.0


def test_hash_exact_declines_on_different_bytes(tmp_path, cfg):
    a = _write(tmp_path / "v1.png", _textured(1))
    b = _write(tmp_path / "probe.png", _textured(2))
    cset = CandidateSet("P", (_candidate("1", a, 1),))

    outcome = HashExactStage().run(_ctx(b, cset, cfg))

    assert not outcome.decisive
    assert outcome.matched is None


# --------------------------------------------------------------------------
# whole_image
# --------------------------------------------------------------------------


def test_whole_image_answers_when_exactly_one_candidate_is_clean(tmp_path, cfg):
    base = _textured(3)
    same = _write(tmp_path / "v1.png", base)
    # Grossly different: half the canvas repainted.
    other = _write(tmp_path / "v2.png",
                   _with_patch(base, (0, 0, SIZE, SIZE // 2), (10, 200, 10)))
    probe = _write(tmp_path / "probe.png", base)

    cset = CandidateSet("P", (_candidate("1", same, 1), _candidate("2", other, 2)))
    outcome = WholeImageStage().run(_ctx(probe, cset, cfg))

    assert outcome.decisive
    assert outcome.matched.id == "1"
    assert outcome.evidence["clean_ids"] == ["1"]


def test_whole_image_declines_when_no_candidate_is_clean(tmp_path, cfg):
    base = _textured(4)
    a = _write(tmp_path / "v1.png", base)
    b = _write(tmp_path / "v2.png",
               _with_patch(base, (0, 0, SIZE, SIZE // 2), (10, 200, 10)))
    # Unlike either candidate everywhere — not a variant of the same artwork.
    # Two textured images share their grid and differ over a few percent of the
    # canvas, which is well inside the clean cutoff.
    rng = np.random.default_rng(42)
    probe = _write(tmp_path / "probe.png",
                   rng.integers(0, 255, (SIZE, SIZE, 3), dtype=np.uint8))

    cset = CandidateSet("P", (_candidate("1", a, 1), _candidate("2", b, 2)))
    outcome = WholeImageStage().run(_ctx(probe, cset, cfg))

    assert not outcome.decisive
    assert outcome.evidence["clean_ids"] == []


def test_whole_image_declines_when_several_are_clean(tmp_path, cfg):
    """Two candidates differing only in a tiny box are both clean globally.

    This is the case the whole-image screen exists to hand over rather than guess:
    the difference between the candidates is smaller than compression noise.
    """
    base = _textured(5)
    a = _write(tmp_path / "v1.png", base)
    b = _write(tmp_path / "v2.png", _with_patch(base, (100, 100, 6, 6), (0, 0, 0)))
    probe = _write(tmp_path / "probe.png", base)

    cset = CandidateSet("P", (_candidate("1", a, 1), _candidate("2", b, 2)))
    outcome = WholeImageStage().run(_ctx(probe, cset, cfg))

    assert not outcome.decisive
    assert len(outcome.evidence["clean_ids"]) == 2


# --------------------------------------------------------------------------
# discriminating_region
# --------------------------------------------------------------------------


def test_region_stage_picks_the_candidate_unchanged_in_the_box(tmp_path, cfg):
    """The whole point: rank inside the box the candidates are known to differ in."""
    base = _textured(6)
    box = (100, 100, 30, 30)
    a = _write(tmp_path / "v1.png", base)
    b = _write(tmp_path / "v2.png", _with_patch(base, box, (255, 0, 0)))
    probe = _write(tmp_path / "probe.png", base)      # a copy of v1

    from core.types import Discriminator
    cset = CandidateSet(
        "P", (_candidate("1", a, 1), _candidate("2", b, 2)),
        (Discriminator("1", "2", box),))

    outcome = DiscriminatingRegionStage().run(_ctx(probe, cset, cfg))

    assert outcome.decisive
    assert outcome.matched.id == "1"
    assert outcome.evidence["totals"]["1"] < outcome.evidence["totals"]["2"]


def test_region_stage_refuses_when_the_margin_is_not_cleared(tmp_path, cfg):
    """Near a tie the ranking is barely better than a coin toss, so it must refuse.

    The two candidates differ inside the box, but only just — and the probe matches
    neither of them there. Both score high and almost equally, so no candidate
    clears the margin and the honest answer is that the evidence does not say.
    """
    base = _textured(7)
    box = (100, 100, 30, 30)
    a = _write(tmp_path / "v1.png", _with_patch(base, box, (255, 0, 0)))
    b = _write(tmp_path / "v2.png", _with_patch(base, box, (250, 0, 0)))
    probe = _write(tmp_path / "probe.png", base)   # unpainted: unlike both

    from core.types import Discriminator
    cset = CandidateSet(
        "P", (_candidate("1", a, 1), _candidate("2", b, 2)),
        (Discriminator("1", "2", box),))

    outcome = DiscriminatingRegionStage().run(_ctx(probe, cset, cfg))

    totals = outcome.evidence["totals"]
    assert min(totals.values()) > 0, "both candidates should differ from the probe"
    assert not outcome.decisive
    assert outcome.evidence["refused_on"] == "margin"


# --------------------------------------------------------------------------
# single_candidate — the first-deployment defect
# --------------------------------------------------------------------------


def test_single_candidate_accepts_a_faithful_copy(tmp_path, cfg):
    base = _textured(8)
    only = _write(tmp_path / "v1.png", base)
    probe = _write(tmp_path / "probe.png", base)

    cset = CandidateSet("P", (_candidate("1", only, 1),))
    outcome = SingleCandidateStage().run(_ctx(probe, cset, cfg))

    assert outcome.decisive
    assert outcome.matched.id == "1"


def test_single_candidate_refuses_an_unrelated_image(tmp_path, cfg):
    """The regression this whole stage exists for.

    With one registered version the previous implementation accepted the only
    candidate unconditionally, so a foreign image and even random noise came back
    as a clean match.
    """
    only = _write(tmp_path / "v1.png", _textured(9))
    rng = np.random.default_rng(0)
    probe = _write(tmp_path / "probe.png",
                   rng.integers(0, 255, (SIZE, SIZE, 3), dtype=np.uint8))

    cset = CandidateSet("P", (_candidate("1", only, 1),))
    outcome = SingleCandidateStage().run(_ctx(probe, cset, cfg))

    assert not outcome.decisive
    assert outcome.matched is None
    assert outcome.evidence["refused_on"] == "lone_candidate_unlike_probe"


def test_engine_refuses_a_foreign_image_against_a_single_version_registry(
        tmp_path, cfg):
    """End to end through the engine, which is where the old bug was visible."""
    only = _write(tmp_path / "v1.png", _textured(10))
    rng = np.random.default_rng(1)
    probe_path = _write(tmp_path / "probe.png",
                        rng.integers(0, 255, (SIZE, SIZE, 3), dtype=np.uint8))

    cset = CandidateSet("P", (_candidate("1", only, 1),))
    result = Engine(config=cfg).identify(
        Probe(path=probe_path, content_hash=sha256_file(probe_path)), cset)

    assert result.matched is None
    assert result.method == "NONE"
    assert result.confidence == 0.0
    # Every stage should have been consulted and declined, not skipped silently.
    assert {r.stage for r in result.trace} >= {"hash_exact", "whole_image",
                                               "single_candidate"}


def test_engine_reports_the_deciding_stage_in_its_trace(tmp_path, cfg):
    base = _textured(11)
    only = _write(tmp_path / "v1.png", base)
    probe_path = _write(tmp_path / "probe.png", base)

    cset = CandidateSet("P", (_candidate("1", only, 1),))
    result = Engine(config=cfg).identify(
        Probe(path=probe_path, content_hash=sha256_file(probe_path)), cset)

    assert result.matched.id == "1"
    assert result.method == "HASH_EXACT"
    assert result.trace[-1].decisive
    assert result.trace[-1].stage == "hash_exact"
