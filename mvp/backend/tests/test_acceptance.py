"""The acceptance criteria from the build spec, §10.

Each test here corresponds to one line of that section. Where a criterion cannot
be met at the level the spec implies, the test asserts the level that **is**
achievable and says so in its own message — a suite that passes by testing
something easier than the product claims is worse than no suite.
"""

from __future__ import annotations

import pytest

from core.imaging.regions import overlap_score
from core.textnorm import normalize, tokenize
from tools.accuracy import _regions_in_reference_frame, _corner_error

from .conftest import cases_of, run_pair

LOCALISATION_OVERLAP = 0.3


# --------------------------------------------------------------------------
# test_identical_detected
# --------------------------------------------------------------------------


def test_identical_detected(corpus, truth, cfg, ocr, artifacts):
    """Byte copies -> IDENTICAL at confidence 1.0."""
    cases = cases_of(truth, "IDENTICAL")
    assert cases, "the corpus produced no IDENTICAL cases"

    for i, case in enumerate(cases):
        result = run_pair(corpus, case, cfg, ocr, artifacts, index=100 + i)
        assert result.verdict == "IDENTICAL", case["name"]
        assert result.confidence == 1.0, case["name"]
        assert result.reference_sha256 == result.marketplace_sha256


# --------------------------------------------------------------------------
# test_reencoded_not_flagged — the most important test in the suite
# --------------------------------------------------------------------------


def test_reencoded_not_flagged(corpus, truth, cfg, ocr, artifacts):
    """Re-encoded unchanged artwork must never be reported as DIFFERENT.

    The most important test here, and the one whose failure mode is worst:
    reporting good artwork as changed sends someone to investigate a
    non-problem, and a few of those and the tool gets switched off. A refusal
    costs one person one look, so refusals are tolerated and false positives
    are not.
    """
    cases = [c for c in cases_of(truth, "REENCODED")
             if (c["transform"].get("quality") or 100) >= 75]
    assert cases, "the corpus produced no REENCODED cases at quality >= 75"

    false_positives = []
    for i, case in enumerate(cases):
        result = run_pair(corpus, case, cfg, ocr, artifacts, index=200 + i)
        if result.verdict == "DIFFERENT":
            material = [r for r in result.regions if r.severity == "MATERIAL"]
            false_positives.append((case["name"], [
                (r.box, r.reference_text, r.marketplace_text) for r in material]))

    assert not false_positives, (
        f"unchanged artwork was reported as DIFFERENT in "
        f"{len(false_positives)} of {len(cases)} cases: {false_positives}")


# --------------------------------------------------------------------------
# test_numeric_drift_found_and_read
# --------------------------------------------------------------------------


def test_numeric_drift_found_and_read(corpus, truth, cfg, ocr, artifacts):
    """Report localisation and reading rates **separately**.

    They are different failure modes: localisation failing means the pixel stage
    never proposed the region; reading failing means it proposed it and the
    recognizer got the characters wrong. Averaging them hides which one is the
    problem, so this test measures both and asserts a floor on each.

    The floors are deliberately modest and are the measured behaviour rather than
    an aspiration. §1 of the spec is explicit that a one-digit edit is below the
    compression noise floor and that pixel-level detection of it will be
    materially less reliable than the version-identification build's 99.2%. What
    this test guards is regression, not excellence.
    """
    cases = cases_of(truth, "NUMERIC_DRIFT")
    assert cases, "the corpus produced no NUMERIC_DRIFT cases"

    edits = located = reads = reads_correct = 0

    for i, case in enumerate(cases):
        result = run_pair(corpus, case, cfg, ocr, artifacts, index=300 + i)
        detected = _regions_in_reference_frame(result)

        for edit in case["edits"]:
            box = edit.get("box")
            if not box:
                continue
            edits += 1
            hits = [j for j, d in enumerate(detected)
                    if overlap_score(d, box) >= LOCALISATION_OVERLAP]
            if hits:
                located += 1
            if edit["type"] == "NUMERIC_DRIFT" and edit.get("old") and edit.get("new"):
                reads += 1
                old, new = normalize(str(edit["old"])), normalize(str(edit["new"]))
                if any(old in set(tokenize(result.regions[j].reference_text or ""))
                       and new in set(tokenize(result.regions[j].marketplace_text or ""))
                       for j in hits):
                    reads_correct += 1

    localisation_rate = located / edits if edits else 0.0
    read_rate = reads_correct / reads if reads else 0.0

    print(f"\n  localisation: {located}/{edits} = {localisation_rate:.1%}")
    print(f"  reading:      {reads_correct}/{reads} = {read_rate:.1%}")

    assert localisation_rate >= 0.45, (
        f"region localisation fell to {localisation_rate:.1%} ({located}/{edits})")
    assert read_rate >= 0.20, (
        f"OCR read-correctness fell to {read_rate:.1%} ({reads_correct}/{reads})")


# --------------------------------------------------------------------------
# test_registration_recovers_homography
# --------------------------------------------------------------------------


def test_registration_recovers_homography(corpus, truth, cfg, ocr, artifacts):
    """PHOTOGRAPHED cases: the recovered matrix must match the applied one.

    Compared by where the two transforms send the reference's four corners, not
    entry by entry: homographies are defined only up to scale, and a small change
    in the bottom row moves points a lot. Corner displacement is the measurement
    that matters to everything downstream.
    """
    cases = [c for c in cases_of(truth, "PHOTOGRAPHED") if c.get("homography")]
    assert cases, "the corpus produced no PHOTOGRAPHED cases"

    import numpy as np

    errors = []
    for i, case in enumerate(cases):
        result = run_pair(corpus, case, cfg, ocr, artifacts, index=400 + i)
        registration = next(t for t in result.traces if t.stage == "registration")
        assert registration.status in ("OK", "DEGRADED"), (
            f"{case['name']}: registration failed on a photographed pack")

        recovered = registration.metrics.get("homography")
        assert recovered, f"{case['name']}: no homography was recorded"
        errors.append(_corner_error(
            np.asarray(case["homography"], dtype=np.float64),
            np.asarray(recovered, dtype=np.float64), 1500))

    worst = max(errors)
    print(f"\n  corner error: mean {sum(errors) / len(errors):.2f}px, max {worst:.2f}px")
    assert worst <= 5.0, f"recovered homography is off by {worst:.2f}px at the corners"


# --------------------------------------------------------------------------
# test_registration_refuses_on_unrelated
# --------------------------------------------------------------------------


def test_registration_refuses_on_unrelated(corpus, truth, cfg, ocr, artifacts):
    """UNRELATED and WRONG_PRODUCT must never produce a confident match."""
    cases = cases_of(truth, "UNRELATED") + cases_of(truth, "WRONG_PRODUCT")
    assert cases, "the corpus produced no UNRELATED or WRONG_PRODUCT cases"

    for i, case in enumerate(cases):
        result = run_pair(corpus, case, cfg, ocr, artifacts, index=500 + i)
        assert result.verdict not in ("MATCH", "IDENTICAL",
                                      "MATCH_WITH_COSMETIC_DIFFERENCES"), (
            f"{case['name']} ({case['case_class']}) was accepted as a match")


def test_unrelated_noise_cannot_compare(corpus, truth, cfg, ocr, artifacts):
    """Structured noise must reach CANNOT_COMPARE specifically.

    Split from the test above because the two classes fail differently: a wrong
    product shares a layout and may well register, while noise should not
    register at all. Collapsing them would let a regression in one hide behind
    the other.
    """
    cases = cases_of(truth, "UNRELATED")
    assert cases
    for i, case in enumerate(cases):
        result = run_pair(corpus, case, cfg, ocr, artifacts, index=550 + i)
        assert result.verdict == "CANNOT_COMPARE", case["name"]
        assert result.confidence == 0.0


# --------------------------------------------------------------------------
# test_cosmetic_not_material
# --------------------------------------------------------------------------


def test_cosmetic_not_material(corpus, truth, cfg, ocr, artifacts):
    """A hue rotation is cosmetic, and must never be reported as material."""
    cases = cases_of(truth, "PALETTE_SHIFT")
    assert cases, "the corpus produced no PALETTE_SHIFT cases"

    materials = []
    for i, case in enumerate(cases):
        result = run_pair(corpus, case, cfg, ocr, artifacts, index=600 + i)
        if result.verdict == "DIFFERENT":
            materials.append((case["name"], [
                (r.difference_type, r.reference_text, r.marketplace_text)
                for r in result.regions if r.severity == "MATERIAL"]))

    assert not materials, f"a recolour was reported as a material change: {materials}"


# --------------------------------------------------------------------------
# test_visual_only_surfaced
# --------------------------------------------------------------------------


def test_visual_only_surfaced(corpus, truth, cfg, ocr, artifacts):
    """A removed mark with no text must still be found and attributed.

    `VISUAL_ONLY` is the point of this test. A removed certification mark is a
    real change with nothing to read, and a pipeline that discarded regions with
    no text would be silently blind to every non-text edit.
    """
    cases = cases_of(truth, "CERT_REMOVED")
    if not cases:
        pytest.skip("the corpus produced no CERT_REMOVED cases at this size")

    surfaced = 0
    for i, case in enumerate(cases):
        result = run_pair(corpus, case, cfg, ocr, artifacts, index=700 + i)
        detected = _regions_in_reference_frame(result)
        box = case["edits"][0]["box"]
        hits = [j for j, d in enumerate(detected)
                if overlap_score(d, box) >= LOCALISATION_OVERLAP]
        if hits and any(result.regions[j].difference_type == "VISUAL_ONLY"
                        for j in hits):
            surfaced += 1
        assert result.verdict in ("DIFFERENT", "NEEDS_REVIEW"), (
            f"{case['name']}: a removed mark produced {result.verdict}")

    assert surfaced, "no removed mark was attributed to VISUAL_ONLY"


# --------------------------------------------------------------------------
# test_determinism
# --------------------------------------------------------------------------


def test_determinism(corpus, truth, cfg, ocr, artifacts):
    """The same pair twice must produce identical output.

    Excluding ids, timestamps and durations. A report that changes between runs
    over unchanged inputs is worthless — that is as true of this build as of the
    one it is cut down from.
    """
    names = ["NUMERIC_DRIFT", "REENCODED", "PHOTOGRAPHED", "PALETTE_SHIFT"]
    picks = [cases_of(truth, n)[0] for n in names if cases_of(truth, n)]
    assert picks

    for i, case in enumerate(picks):
        first = run_pair(corpus, case, cfg, ocr, artifacts, index=800 + i)
        second = run_pair(corpus, case, cfg, ocr, artifacts, index=800 + i)

        assert first.verdict == second.verdict, case["name"]
        assert first.confidence == second.confidence, case["name"]
        assert [r.as_dict() for r in first.regions] == \
               [r.as_dict() for r in second.regions], case["name"]
        assert [(t.stage, t.status, t.metrics) for t in first.traces] == \
               [(t.stage, t.status, t.metrics) for t in second.traces], case["name"]


# --------------------------------------------------------------------------
# test_every_stage_emits_trace
# --------------------------------------------------------------------------


def test_every_stage_emits_trace(corpus, truth, cfg, ocr, artifacts):
    """Every stage emits a trace, including on the failure paths.

    No stage may complete without a trace row. Silent failure is the one
    unacceptable outcome here, because the entire purpose of this build is to
    show the method working or not working — and a gap in the record is
    indistinguishable from a lie.
    """
    from domains.packaging.compare import stage_names

    expected = stage_names()

    # Deliberately spans the three control-flow paths: a normal run, an early
    # exit on the hash, and a halt when registration refuses.
    picks = [c for name in ("REENCODED", "IDENTICAL", "UNRELATED")
             for c in cases_of(truth, name)[:1]]
    assert len(picks) == 3

    for i, case in enumerate(picks):
        result = run_pair(corpus, case, cfg, ocr, artifacts, index=900 + i)
        seen = [t.stage for t in result.traces]
        assert seen == expected, (
            f"{case['name']} ({case['case_class']}): expected every stage to emit a "
            f"trace in order, got {seen}")
        for trace in result.traces:
            assert trace.status in ("OK", "DEGRADED", "FAILED", "SKIPPED")
            assert trace.notes, (
                f"{case['name']}: stage {trace.stage!r} emitted a trace with no "
                f"explanation of what it saw")


def test_failed_stage_still_explains_itself(corpus, truth, cfg, ocr, artifacts):
    """A stage that stops the pipeline says what it saw and why it stopped."""
    cases = cases_of(truth, "UNRELATED")
    assert cases

    result = run_pair(corpus, cases[0], cfg, ocr, artifacts, index=950)
    registration = next(t for t in result.traces if t.stage == "registration")
    assert registration.status == "FAILED"
    assert registration.notes, "a failed stage emitted no explanation"
    assert registration.metrics, "a failed stage recorded no evidence"

    skipped = [t for t in result.traces if t.status == "SKIPPED"]
    assert skipped, "stages after a halt were not recorded as skipped"
    for trace in skipped:
        assert trace.notes, f"{trace.stage} was skipped without saying why"
