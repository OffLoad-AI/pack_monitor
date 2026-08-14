"""Acceptance tests for version identification (§11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from db.models import DiscriminatingRegion, Finding, ScrapedImage
from db.session import SessionLocal
from pipeline import diff as D
from tools.accuracy import evaluate

# The spec's bar: >98% identification and zero false alarms at q>=75.
MIN_ACCURACY_Q75 = 0.98


@pytest.fixture(scope="module")
def report(baseline):
    baseline.activate()
    return evaluate(baseline.corpus, baseline.run_id)


def test_hash_exact_match(baseline, manifest):
    """An untouched byte copy is identified with confidence 1.0 via HASH_EXACT."""
    baseline.activate()
    untouched = {n for n, m in manifest.items() if m.get("untouched")}
    assert untouched, "corpus must contain byte-identical copies"

    with SessionLocal() as db:
        rows = db.execute(
            select(Finding, ScrapedImage)
            .join(ScrapedImage, Finding.scraped_image_id == ScrapedImage.id)
            .where(Finding.run_id == baseline.run_id)).all()

    checked = 0
    for finding, img in rows:
        if Path(img.source_path).name not in untouched:
            continue
        checked += 1
        assert finding.match_method == "HASH_EXACT", (
            f"{Path(img.source_path).name} matched via {finding.match_method}")
        assert finding.confidence == 1.0
        assert finding.matched_version_id is not None
    assert checked == len(untouched)


def test_version_identification_across_transforms(report):
    """Every file in variants_manifest.json is matched to its true source version."""
    overall = report["overall"]
    print(f"\n  overall {overall['correct']}/{overall['total']} "
          f"= {100 * overall['correct'] / overall['total']:.2f}%")

    print("  by JPEG quality:")
    for q in sorted(report["by_quality"], key=lambda x: (x is None, x)):
        d = report["by_quality"][q]
        print(f"    {'untouched' if q is None else f'q{q}':<10} "
              f"{100 * d['correct'] / d['total']:6.2f}%  ({d['correct']}/{d['total']})")
    print("  by output size:")
    for s in sorted(report["by_size"]):
        d = report["by_size"][s]
        print(f"    {s}x{s:<6} {100 * d['correct'] / d['total']:6.2f}%  "
              f"({d['correct']}/{d['total']})")

    failures = []
    for q, d in report["by_quality"].items():
        if q is None or q < 75:
            continue
        rate = d["correct"] / d["total"]
        if rate < MIN_ACCURACY_Q75:
            failures.append(f"q{q}: {100 * rate:.2f}% ({d['correct']}/{d['total']})")

    assert not failures, (
        "identification accuracy below 98% at q>=75 for " + "; ".join(failures))


def test_no_false_positives_on_reencoding(report):
    """Unchanged artwork re-encoded at any quality must not be reported stale.

    The most important test in the suite. A tool that cries wolf is abandoned, so
    the bar is zero false alarms — not a low rate.
    """
    print(f"\n  approved-artwork images: {report['pass_expected']}")
    print(f"  reported STALE (false alarms): {report['false_positives']} "
          f"[q>=75: {report['false_positives_q75plus']}]")
    print(f"  not identified (refusals):     {report['declined']} "
          f"[q>=75: {report['declined_q75plus']}]")

    assert report["false_positives_q75plus"] == 0, (
        f"{report['false_positives_q75plus']} images of approved artwork were "
        f"reported as STALE_VERSION at q>=75")


def test_numeric_drift_detected(baseline, ground_truth):
    """Every NUMERIC_DRIFT edit is reported, with the right region and old->new."""
    baseline.activate()
    with SessionLocal() as db:
        regions = db.scalars(select(DiscriminatingRegion)).all()

    by_product: dict[str, list[DiscriminatingRegion]] = {}
    for r in regions:
        by_product.setdefault(r.product_id, []).append(r)

    expected = 0
    missing = []
    for sku, gt in ground_truth.items():
        for transition, edits in gt["transitions"].items():
            for edit in edits:
                if edit["type"] != "NUMERIC_DRIFT" or not edit.get("box"):
                    continue
                expected += 1
                hit = None
                for r in by_product.get(sku, []):
                    if r.edit_type != "NUMERIC_DRIFT":
                        continue
                    overlap = max(D.iou(r, edit["box"]), D.containment(r, edit["box"]))
                    if overlap > 0.3 and r.field_key == edit["field"]:
                        hit = r
                        break
                if hit is None:
                    missing.append(f"{sku} {transition} {edit['field']}")
                    continue
                assert hit.old_value == edit["old"], (
                    f"{sku} {edit['field']}: old {hit.old_value} != {edit['old']}")
                assert hit.new_value == edit["new"], (
                    f"{sku} {edit['field']}: new {hit.new_value} != {edit['new']}")
                assert hit.severity == "MATERIAL"

    assert expected > 0, "corpus contains no NUMERIC_DRIFT edits to check"
    assert not missing, f"{len(missing)}/{expected} numeric drifts undetected: {missing[:5]}"
    print(f"\n  {expected} numeric drifts, all detected with correct field and values")


def test_numeric_drift_reaches_findings(baseline, ground_truth):
    """A stale listing's findings carry the drifted field and its old->new values."""
    baseline.activate()
    with SessionLocal() as db:
        findings = db.scalars(
            select(Finding).where(Finding.run_id == baseline.run_id,
                                  Finding.verdict == "STALE_VERSION")).all()

    drift_fields = {
        (sku, e["field"], e["old"], e["new"])
        for sku, gt in ground_truth.items()
        for edits in gt["transitions"].values()
        for e in edits if e["type"] == "NUMERIC_DRIFT" and e.get("box")
    }
    assert drift_fields

    reported = set()
    for f in findings:
        for r in json.loads(f.regions_json or "[]"):
            if r.get("edit_type") == "NUMERIC_DRIFT":
                reported.add((f.product_id, r["field_key"], r["old"], r["new"]))

    unreported = drift_fields - reported
    assert not unreported, (
        f"{len(unreported)} numeric drifts never surfaced in a finding: "
        f"{sorted(unreported)[:5]}")


def test_cosmetic_not_flagged_as_material(baseline):
    """PALETTE_SHIFT and LOGO_NUDGE are classified COSMETIC, never MATERIAL."""
    baseline.activate()
    with SessionLocal() as db:
        regions = db.scalars(
            select(DiscriminatingRegion)
            .where(DiscriminatingRegion.edit_type.in_(["PALETTE_SHIFT", "LOGO_NUDGE"]))).all()
        findings = db.scalars(
            select(Finding).where(Finding.run_id == baseline.run_id)).all()

    assert regions, "corpus contains no cosmetic edits to check"
    wrong = [(r.product_id, r.edit_type, r.severity)
             for r in regions if r.severity != "COSMETIC"]
    assert not wrong, f"cosmetic edits classified otherwise: {wrong[:5]}"

    # And a finding whose every delta is cosmetic must itself be COSMETIC.
    for f in findings:
        deltas = json.loads(f.regions_json or "[]")
        if not deltas:
            continue
        if all(d["severity"] == "COSMETIC" for d in deltas):
            assert f.severity == "COSMETIC", (
                f"finding {f.id} has only cosmetic deltas but severity {f.severity}")
    print(f"\n  {len(regions)} cosmetic regions, all COSMETIC")
