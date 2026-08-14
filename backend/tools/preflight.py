"""Check that real artwork and real listing images satisfy the method's premises.

The pipeline assumes three things that a synthetic corpus guarantees by
construction and real data does not:

1. **The reference and the listing came from the same file.** If the brand's
   artwork and the marketplace image are separate renders, no stage can identify
   a version and everything lands in `UNKNOWN_IMAGE`.
2. **Border cropping finds the same content rectangle in both.** Uniform-border
   cropping is colour-agnostic and strips inward until the line stops being
   uniform. Artwork with a plain edge is itself uniform, so the crop can eat into
   it — by a different amount on each side of the comparison, which leaves the two
   at different scales and smears every glyph into a false difference. §4.
3. **Consecutive versions actually differ somewhere.** If two versions produce no
   discriminating regions, Stage 4 has nothing to rank on.

This reports all three before a run, rather than leaving them to be inferred from
a pile of refusals afterwards.

    python -m tools.preflight --dir ../data/real
    python -m tools.preflight --dir ../data/real --input ../data/real/scraped/run_01
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from pipeline import diff as D
from pipeline import normalize as N
from pipeline.config import load_thresholds

# A reference is meant to be edge-to-edge artwork: cropping should find nothing.
# Past this, uniform-border detection is eating into the artwork itself.
REF_CROP_WARN = 0.02
# Aspect ratios should agree once both are de-padded; they came from one file.
ASPECT_WARN = 0.01


def crop_report(path: Path, cfg: dict) -> dict:
    rgb = N.load_rgb(path)
    h, w = rgb.shape[:2]
    rect = N.detect_content_rect(rgb, cfg["border_uniform_tolerance"],
                                 cfg["max_border_crop_fraction"])
    x0, y0, x1, y1 = rect
    cw, ch = x1 - x0, y1 - y0
    return {
        "path": path,
        "raw": (w, h),
        "content": (round(cw, 1), round(ch, 1)),
        "cropped_fraction": round(1.0 - (cw * ch) / (w * h), 4),
        "aspect": cw / ch if ch else 0.0,
    }


def check_references(root: Path, cfg: dict) -> int:
    gt = json.loads((root / "ground_truth.json").read_text())
    problems = 0

    print("=" * 72)
    print("REFERENCES — border crop and version separability")
    print("=" * 72)

    for sku in sorted(gt):
        labels = gt[sku]["versions"]
        print(f"\n{sku}  ({len(labels)} versions, current {gt[sku]['current']})")

        images = {}
        for lab in labels:
            p = (root / gt[sku]["files"][lab]).resolve()
            r = crop_report(p, cfg)
            images[lab] = N.load_rgb(p)
            flag = ""
            if r["cropped_fraction"] > REF_CROP_WARN:
                flag = "  <-- border crop is eating the artwork"
                problems += 1
            print(f"  {lab:<12} {r['raw'][0]}x{r['raw'][1]}"
                  f"  content {r['content'][0]}x{r['content'][1]}"
                  f"  cropped {r['cropped_fraction']:.1%}{flag}")

        sizes = {(im.shape[1], im.shape[0]) for im in images.values()}
        if len(sizes) > 1:
            print(f"  ! versions have different dimensions: {sorted(sizes)}")
            print(f"    region coordinates are stored in reference pixel space, so "
                  f"a chain of mixed sizes will misplace boxes")
            problems += 1

        for a, b in zip(labels, labels[1:]):
            if images[a].shape != images[b].shape:
                print(f"  {a}->{b}: skipped, dimensions differ")
                continue
            regions = D.reference_regions(images[a], images[b], cfg)
            area = sum(r["w"] * r["h"] for r in regions)
            total = images[a].shape[0] * images[a].shape[1]
            if not regions:
                print(f"  {a}->{b}: NO discriminating regions — these versions are "
                      f"indistinguishable to Stage 4")
                problems += 1
            else:
                print(f"  {a}->{b}: {len(regions)} region(s), "
                      f"{area / total:.2%} of canvas")
    return problems


def check_listings(input_dir: Path, root: Path, cfg: dict, sample: int) -> int:
    gt = json.loads((root / "ground_truth.json").read_text())
    manifest_path = input_dir / "scrape_manifest.json"
    mapping = {}
    if manifest_path.exists():
        raw = json.loads(manifest_path.read_text())
        mapping = {k: v["product_id"] for k, v in raw.items()}

    files = [p for p in sorted(input_dir.iterdir())
             if p.is_file() and p.suffix.lower() in
             {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}]

    print("\n" + "=" * 72)
    print("LISTINGS — do they de-pad to the same shape as their references?")
    print("=" * 72)

    if not files:
        print(f"no images in {input_dir}")
        return 1

    unmapped = [p.name for p in files
                if mapping.get(p.name, p.name.split("__")[0]) not in gt]
    if unmapped:
        print(f"\n! {len(unmapped)} file(s) map to no registered product and will be "
              f"skipped by the run, e.g. {unmapped[:3]}")

    problems = 0
    shown = 0
    for p in files:
        pid = mapping.get(p.name, p.name.split("__")[0])
        if pid not in gt or shown >= sample:
            continue
        shown += 1

        r = crop_report(p, cfg)
        ref_label = gt[pid]["current"]
        ref = N.load_rgb((root / gt[pid]["files"][ref_label]).resolve())
        ref_rect = N.detect_content_rect(ref, cfg["border_uniform_tolerance"],
                                         cfg["max_border_crop_fraction"])
        ref_aspect = ((ref_rect[2] - ref_rect[0]) /
                      (ref_rect[3] - ref_rect[1])) if ref_rect[3] > ref_rect[1] else 0

        notes = []
        if ref_aspect and abs(r["aspect"] - ref_aspect) / ref_aspect > ASPECT_WARN:
            notes.append(f"aspect {r['aspect']:.3f} vs reference {ref_aspect:.3f}")
            problems += 1

        # The premise check: normalized against its own current artwork, a listing
        # should differ by roughly compression noise, not by structure.
        scraped = N.normalize_scraped(p, cfg)
        s, rr, _scale = N.prepare_pair(scraped.rgb, ref, cfg)
        score = D.diff_score(s, rr, cfg)
        frac = D.changed_fraction(score, 1.0, cfg["morph_open"])
        if frac > cfg["clean_fraction"]:
            notes.append(f"differs from current artwork over {frac:.1%} of pixels")

        print(f"\n  {p.name}  [{pid}]")
        print(f"    {r['raw'][0]}x{r['raw'][1]} -> content "
              f"{r['content'][0]}x{r['content'][1]}  "
              f"(padding stripped: {r['cropped_fraction']:.1%})")
        print(f"    vs {ref_label}: changed fraction {frac:.4f} "
              f"(clean cutoff {cfg['clean_fraction']:.4f})")
        for n in notes:
            print(f"    ! {n}")

    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.preflight")
    ap.add_argument("--dir", required=True,
                    help="directory holding ground_truth.json (see tools.ingest)")
    ap.add_argument("--input", help="a scraped listing directory to sample")
    ap.add_argument("--sample", type=int, default=8,
                    help="how many listing images to inspect (default 8)")
    args = ap.parse_args(argv)

    cfg = load_thresholds()
    root = Path(args.dir).resolve()

    problems = check_references(root, cfg)
    if args.input:
        problems += check_listings(Path(args.input).resolve(), root, cfg,
                                   args.sample)

    print("\n" + "=" * 72)
    if problems:
        print(f"{problems} issue(s) flagged above. A run will still execute, but "
              f"expect refusals where they were flagged.")
    else:
        print("No issues found. Register with pipeline.references, then run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
