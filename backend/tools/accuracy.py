"""Measure version-identification accuracy against the corpus ground truth.

This is the number that matters. `variants_manifest.json` records the true source
version of every scraped file; the pipeline never sees it. Everything here is a
comparison between what the pipeline concluded and what is actually true.

    python -m tools.accuracy --corpus ./data/corpus --run 1
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from db.models import ArtworkVersion, Finding, Run, ScrapedImage
from db.session import SessionLocal


def _fmt_pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:6.2f}% ({n}/{d})" if d else "     n/a"


def evaluate(corpus: Path, run_id: int | None = None) -> dict:
    manifest = json.loads((corpus / "variants_manifest.json").read_text())
    ground_truth = json.loads((corpus / "ground_truth.json").read_text())

    with SessionLocal() as db:
        if run_id is None:
            run_id = db.scalar(select(Run.id).order_by(Run.id.desc()).limit(1))
        rows = db.execute(
            select(Finding, ScrapedImage)
            .join(ScrapedImage, Finding.scraped_image_id == ScrapedImage.id)
            .where(Finding.run_id == run_id)
        ).all()
        versions = {v.id: v for v in db.scalars(select(ArtworkVersion)).all()}
        # Group version ids by (product, sha) so byte-identical versions under
        # different labels count as the same artwork.
        sha_by_id = {v.id: v.sha256 for v in versions.values()}
        label_by_id = {v.id: v.version_label for v in versions.values()}
        by_product_label = defaultdict(dict)
        for v in versions.values():
            by_product_label[v.product_id][v.version_label] = v

    overall = {"total": 0, "correct": 0}
    by_quality: dict = defaultdict(lambda: {"total": 0, "correct": 0})
    by_size: dict = defaultdict(lambda: {"total": 0, "correct": 0})
    by_padding: dict = defaultdict(lambda: {"total": 0, "correct": 0})
    by_format: dict = defaultdict(lambda: {"total": 0, "correct": 0})
    by_method: dict = defaultdict(lambda: {"total": 0, "correct": 0})
    verdicts: dict = defaultdict(int)
    failures: list[dict] = []

    false_positives = 0
    fp_at_q75plus = 0
    declined = 0
    declined_at_q75plus = 0
    pass_expected = 0

    for finding, img in rows:
        meta = manifest.get(Path(img.source_path).name)
        if meta is None:
            continue
        true_label = meta["true_version"]
        product = meta["product_id"]
        true_v = by_product_label[product].get(true_label)
        if true_v is None:
            continue

        matched = finding.matched_version_id
        # Byte-identical artwork under another label is the same artwork.
        correct = matched is not None and (
            matched == true_v.id or sha_by_id.get(matched) == true_v.sha256)

        q = meta["quality"]
        size = meta["size"][0]
        overall["total"] += 1
        overall["correct"] += int(correct)
        by_quality[q]["total"] += 1
        by_quality[q]["correct"] += int(correct)
        by_size[size]["total"] += 1
        by_size[size]["correct"] += int(correct)
        by_padding[meta["padding"] or "none"]["total"] += 1
        by_padding[meta["padding"] or "none"]["correct"] += int(correct)
        by_format[meta["format"]]["total"] += 1
        by_format[meta["format"]]["correct"] += int(correct)
        by_method[finding.match_method]["total"] += 1
        by_method[finding.match_method]["correct"] += int(correct)
        verdicts[finding.verdict] += 1

        # Two very different failures, kept apart deliberately. Reporting approved
        # artwork as stale is crying wolf and is what gets a tool abandoned.
        # Declining to identify it is a refusal: no false alarm reaches the
        # reviewer, the image simply routes to the fallback track. Summing them
        # into one "false positive" number would overstate the first and hide the
        # second.
        is_current_artwork = true_v.sha256 == next(
            (v.sha256 for v in by_product_label[product].values() if v.is_current), None)
        if is_current_artwork:
            pass_expected += 1
            if finding.verdict == "STALE_VERSION":
                false_positives += 1
                if q is None or q >= 75:
                    fp_at_q75plus += 1
            elif finding.verdict != "PASS":
                declined += 1
                if q is None or q >= 75:
                    declined_at_q75plus += 1

        if not correct:
            failures.append({
                "file": Path(img.source_path).name,
                "product": product,
                "true_version": true_label,
                "matched": label_by_id.get(matched),
                "verdict": finding.verdict,
                "method": finding.match_method,
                "quality": q, "size": size,
                "padding": meta["padding"], "format": meta["format"],
            })

    return {
        "run_id": run_id,
        "overall": overall,
        "by_quality": dict(by_quality),
        "by_size": dict(by_size),
        "by_padding": dict(by_padding),
        "by_format": dict(by_format),
        "by_method": dict(by_method),
        "verdicts": dict(verdicts),
        "false_positives": false_positives,
        "false_positives_q75plus": fp_at_q75plus,
        "declined": declined,
        "declined_q75plus": declined_at_q75plus,
        "pass_expected": pass_expected,
        "failures": failures,
    }


def print_report(r: dict) -> None:
    o = r["overall"]
    print(f"\nVersion identification accuracy — run {r['run_id']}")
    print("=" * 62)
    print(f"  overall                    {_fmt_pct(o['correct'], o['total'])}")

    print("\n  by JPEG quality")
    for q in sorted(r["by_quality"], key=lambda x: (x is None, x)):
        d = r["by_quality"][q]
        label = "untouched" if q is None else f"q{q}"
        print(f"    {label:<10}               {_fmt_pct(d['correct'], d['total'])}")

    print("\n  by output size")
    for s in sorted(r["by_size"]):
        d = r["by_size"][s]
        print(f"    {s}x{s:<8}            {_fmt_pct(d['correct'], d['total'])}")

    print("\n  by padding")
    for k in sorted(r["by_padding"]):
        d = r["by_padding"][k]
        print(f"    {k:<22}   {_fmt_pct(d['correct'], d['total'])}")

    print("\n  by format")
    for k in sorted(r["by_format"]):
        d = r["by_format"][k]
        print(f"    {k:<22}   {_fmt_pct(d['correct'], d['total'])}")

    print("\n  by match method")
    for k in sorted(r["by_method"]):
        d = r["by_method"][k]
        print(f"    {k:<22}   {_fmt_pct(d['correct'], d['total'])}")

    print(f"\n  verdicts: {r['verdicts']}")
    print(f"  false alarms (approved artwork reported STALE): "
          f"{r['false_positives']}/{r['pass_expected']}  "
          f"[at q>=75: {r['false_positives_q75plus']}]")
    print(f"  refusals    (approved artwork not identified):  "
          f"{r['declined']}/{r['pass_expected']}  "
          f"[at q>=75: {r['declined_q75plus']}]")

    if r["failures"]:
        print(f"\n  {len(r['failures'])} misidentified — first 15:")
        for f in r["failures"][:15]:
            print(f"    {f['file'][:58]:60s} true={f['true_version']:<4} "
                  f"got={f['matched']} verdict={f['verdict']} method={f['method']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.accuracy")
    ap.add_argument("--corpus", default="./data/corpus")
    ap.add_argument("--run", type=int, default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    r = evaluate(Path(args.corpus).resolve(), args.run)
    print_report(r)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
