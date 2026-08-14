"""Ground-truth evaluation of the pairwise corpus.

    python -m tools.accuracy --pairs ../data/pairs --out ../RESULTS.json

Reports **region localisation** and **OCR read-correctness** as two separate
numbers, and this is not a presentational choice. They are different failure
modes: localisation failing means the pixel stage never proposed the region, and
reading failing means it proposed it and the recognizer got the characters wrong.
The fixes are unrelated, and an average of the two hides which one is the problem.

Likewise **refusals** (`CANNOT_COMPARE`, `NEEDS_REVIEW`) are reported separately
from **false differents**. A refusal costs a reviewer one look; a false `DIFFERENT`
on unchanged artwork costs the tool its credibility, and is the number to watch.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from core.config import load_config
from core.imaging.regions import overlap_score
from core.ocr import get_engine
from core.textnorm import normalize, tokenize
from domains.packaging.compare import compare_pair

# The overlap at which a detected region counts as having found a known edit.
# Max of IoU and containment, following the other build: one logical edit often
# surfaces as several components while ground truth stores a single union box,
# and each small component has terrible IoU against that union.
LOCALISATION_OVERLAP = 0.3


def _trace(result, stage: str):
    for t in result.traces:
        if t.stage == stage:
            return t
    return None


def _homography(result) -> np.ndarray | None:
    t = _trace(result, "registration")
    if t is None:
        return None
    h = t.metrics.get("homography")
    return np.asarray(h, dtype=np.float64) if h else None


def _regions_in_reference_frame(result) -> list[tuple[int, int, int, int]]:
    """Map every detected region back into reference coordinates.

    Ground truth is recorded in the reference's own pixel space, so this is the
    only way to check a detection against it without re-deriving the marketplace
    image's padding and scale — which the pipeline already solved.
    """
    H = _homography(result)
    if H is None:
        return []
    try:
        h_inv = np.linalg.inv(H)
    except np.linalg.LinAlgError:
        return []

    boxes = []
    for r in result.regions:
        x, y, w, h = r.box
        corners = np.float32([[x, y], [x + w, y], [x + w, y + h],
                              [x, y + h]]).reshape(-1, 1, 2)
        mapped = cv2.perspectiveTransform(corners, h_inv).reshape(-1, 2)
        x0, y0 = mapped.min(axis=0)
        x1, y1 = mapped.max(axis=0)
        boxes.append((int(round(x0)), int(round(y0)),
                      int(round(x1 - x0)), int(round(y1 - y0))))
    return boxes


def _corner_error(applied: np.ndarray, recovered: np.ndarray, size: int) -> float:
    """Mean displacement of the four corners under the two transforms, in pixels.

    Comparing matrices entry by entry is meaningless — homographies are only
    defined up to scale and a small change in the bottom row moves points a lot.
    Comparing where they *send the corners* is the measurement that matters.
    """
    src = np.float32([[0, 0], [size, 0], [size, size], [0, size]]).reshape(-1, 1, 2)
    a = cv2.perspectiveTransform(src, applied).reshape(-1, 2)
    b = cv2.perspectiveTransform(src, recovered).reshape(-1, 2)
    return float(np.linalg.norm(a - b, axis=1).mean())


def evaluate(pairs_dir: Path, limit: int | None = None,
             artifacts_root: Path | None = None) -> dict[str, Any]:
    pairs_dir = Path(pairs_dir)
    truth = json.loads((pairs_dir / "ground_truth.json").read_text())
    names = sorted(truth)
    if limit:
        names = names[:limit]

    cfg = load_config()
    engine = get_engine(cfg.ocr.backend, cfg.ocr.det_limit_side_len)
    art_root = Path(artifacts_root) if artifacts_root else pairs_dir / "artifacts"

    rows: list[dict[str, Any]] = []
    stage_times: dict[str, list[float]] = defaultdict(list)

    started = time.perf_counter()
    for i, name in enumerate(names, start=1):
        case = truth[name]
        result = compare_pair(
            pairs_dir / case["reference"], pairs_dir / case["marketplace"],
            comparison_id=i, config=cfg,
            artifacts_root=art_root / name, data_root=art_root,
            ocr_engine=engine)

        for t in result.traces:
            stage_times[t.stage].append(t.duration_ms)

        row = _score_case(case, result, pairs_dir)
        row["duration_ms"] = round(result.duration_ms, 1)
        rows.append(row)

        if i % 10 == 0 or i == len(names):
            print(f"  {i}/{len(names)} pairs", flush=True)

    total_s = time.perf_counter() - started
    return _summarize(rows, stage_times, total_s, engine.name)


def _score_case(case: dict, result, pairs_dir: Path) -> dict[str, Any]:
    acceptable = set(case.get("acceptable_verdicts") or [case["expected_verdict"]])
    acceptable.add(case["expected_verdict"])

    reg = _trace(result, "registration")
    row: dict[str, Any] = {
        "name": case["name"],
        "case_class": case["case_class"],
        "expected": case["expected_verdict"],
        "actual": result.verdict,
        "correct": result.verdict in acceptable,
        "confidence": result.confidence,
        "quality": case["transform"].get("quality"),
        "size": (case["transform"].get("size") or [None])[0],
        "registration_status": reg.status if reg else "MISSING",
        "registered": bool(reg and reg.status in ("OK", "DEGRADED")),
        "inliers": (reg.metrics.get("inliers") if reg else None),
        "regions": len(result.regions),
        "error": result.error,
    }

    # -- false alarm: unchanged artwork reported as changed ------------------
    unchanged = case["case_class"] in ("IDENTICAL", "REENCODED") or (
        case["case_class"] == "PHOTOGRAPHED" and not case["edits"])
    row["unchanged_pair"] = unchanged
    row["false_different"] = bool(unchanged and result.verdict == "DIFFERENT")
    row["refused"] = result.verdict in ("CANNOT_COMPARE", "NEEDS_REVIEW")

    # -- homography recovery -------------------------------------------------
    if case.get("homography"):
        recovered = _homography(result)
        if recovered is not None:
            row["corner_error_px"] = round(_corner_error(
                np.asarray(case["homography"], dtype=np.float64), recovered,
                1500), 2)
        else:
            row["corner_error_px"] = None

    # -- localisation and reading, separately --------------------------------
    if case["edits"]:
        detected = _regions_in_reference_frame(result)
        located, read_ok, expected_reads = 0, 0, 0
        for edit in case["edits"]:
            box = edit.get("box")
            if not box:
                continue
            hits = [i for i, d in enumerate(detected)
                    if overlap_score(d, box) >= LOCALISATION_OVERLAP]
            if hits:
                located += 1
            # Only NUMERIC_DRIFT has an old->new pair to check a reading against.
            if edit["type"] == "NUMERIC_DRIFT" and edit.get("old") and edit.get("new"):
                expected_reads += 1
                if _read_correctly(result, hits, edit):
                    read_ok += 1
        row["edits"] = len(case["edits"])
        row["edits_located"] = located
        row["reads_expected"] = expected_reads
        row["reads_correct"] = read_ok

    return row


def _read_correctly(result, hit_indices: list[int], edit: dict) -> bool:
    """Whether OCR read the old value on the reference and the new one on the
    marketplace image, in a region that actually covers the edit."""
    old = normalize(str(edit["old"]))
    new = normalize(str(edit["new"]))
    for i in hit_indices:
        region = result.regions[i]
        ref_tokens = set(tokenize(region.reference_text or ""))
        mkt_tokens = set(tokenize(region.marketplace_text or ""))
        if old in ref_tokens and new in mkt_tokens:
            return True
    return False


def _summarize(rows, stage_times, total_s, engine_name) -> dict[str, Any]:
    by_class: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "correct": 0, "refused": 0, "false_different": 0,
                 "verdicts": defaultdict(int)})
    by_quality: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "correct": 0})
    by_size: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "correct": 0})

    for r in rows:
        c = by_class[r["case_class"]]
        c["n"] += 1
        c["correct"] += int(r["correct"])
        c["refused"] += int(r["refused"])
        c["false_different"] += int(r["false_different"])
        c["verdicts"][r["actual"]] += 1
        if r["quality"] is not None:
            q = by_quality[str(r["quality"])]
            q["n"] += 1
            q["correct"] += int(r["correct"])
        if r["size"] is not None:
            s = by_size[str(r["size"])]
            s["n"] += 1
            s["correct"] += int(r["correct"])

    edits_total = sum(r.get("edits", 0) for r in rows)
    edits_located = sum(r.get("edits_located", 0) for r in rows)
    reads_expected = sum(r.get("reads_expected", 0) for r in rows)
    reads_correct = sum(r.get("reads_correct", 0) for r in rows)

    photographed = [r for r in rows if r["case_class"] == "PHOTOGRAPHED"]
    corner_errors = [r["corner_error_px"] for r in rows
                     if r.get("corner_error_px") is not None]

    return {
        "engine": engine_name,
        "pairs": len(rows),
        "wall_seconds": round(total_s, 1),
        "seconds_per_pair": round(total_s / max(1, len(rows)), 2),
        "verdict_accuracy": round(sum(r["correct"] for r in rows) / max(1, len(rows)), 4),
        "false_different_count": sum(r["false_different"] for r in rows),
        "unchanged_pairs": sum(r["unchanged_pair"] for r in rows),
        "refusal_count": sum(r["refused"] for r in rows),
        "by_class": {k: {**v, "accuracy": round(v["correct"] / v["n"], 4),
                         "verdicts": dict(v["verdicts"])}
                     for k, v in sorted(by_class.items())},
        "by_jpeg_quality": {k: {**v, "accuracy": round(v["correct"] / v["n"], 4)}
                            for k, v in sorted(by_quality.items())},
        "by_size": {k: {**v, "accuracy": round(v["correct"] / v["n"], 4)}
                    for k, v in sorted(by_size.items())},
        "localisation": {
            "edits": edits_total, "located": edits_located,
            "rate": round(edits_located / edits_total, 4) if edits_total else None},
        "ocr_read_correctness": {
            "expected": reads_expected, "correct": reads_correct,
            "rate": round(reads_correct / reads_expected, 4) if reads_expected else None},
        "registration": {
            "overall_rate": round(
                sum(r["registered"] for r in rows) / max(1, len(rows)), 4),
            "photographed_rate": round(
                sum(r["registered"] for r in photographed) / len(photographed), 4)
            if photographed else None,
            "photographed_corner_error_px": {
                "mean": round(statistics.fmean(corner_errors), 2) if corner_errors else None,
                "median": round(statistics.median(corner_errors), 2) if corner_errors else None,
                "max": round(max(corner_errors), 2) if corner_errors else None,
            },
        },
        "stage_timing_ms": {
            stage: {"mean": round(statistics.fmean(v), 1),
                    "median": round(statistics.median(v), 1),
                    "max": round(max(v), 1)}
            for stage, v in sorted(stage_times.items()) if v},
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.accuracy")
    ap.add_argument("--pairs", default="../data/pairs")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None, help="write the full report as JSON")
    ap.add_argument("--artifacts", default=None)
    args = ap.parse_args(argv)

    report = evaluate(Path(args.pairs), args.limit,
                      Path(args.artifacts) if args.artifacts else None)

    brief = {k: v for k, v in report.items() if k != "cases"}
    print(json.dumps(brief, indent=2))

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nfull report -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
