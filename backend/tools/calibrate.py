"""Milestone 2 — measure the noise floor and derive thresholds.

The threshold separating "this is the same artwork, re-encoded" from "this artwork
was edited" is a property of the encoding pipeline, not something to guess. It is
measured here and written to config/thresholds.json, which the run pipeline reads.
Nothing downstream hardcodes a number.

Luma and chroma are calibrated separately. Their noise floors differ by roughly 3x,
and a single threshold set from the luma floor is blind to a palette change.

    python -m tools.calibrate --corpus ./data/corpus
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

from pipeline import diff as D
from pipeline import normalize as N
from pipeline.config import DEFAULTS, REPO_ROOT, save_thresholds

SAMPLE_PIXELS_PER_PAIR = 120_000


def _pct(v: np.ndarray, q: float) -> float:
    return float(np.percentile(v, q)) if v.size else 0.0


def _subsample(a: np.ndarray, n: int) -> np.ndarray:
    flat = a.reshape(-1)
    if flat.size <= n:
        return flat
    idx = np.linspace(0, flat.size - 1, n).astype(np.int64)
    return flat[idx]


def _index_corpus(corpus: Path):
    ground_truth = json.loads((corpus / "ground_truth.json").read_text())
    manifest = json.loads((corpus / "variants_manifest.json").read_text())
    scraped: dict[str, Path] = {}
    for run_dir in sorted((corpus / "scraped").iterdir()):
        if run_dir.is_dir():
            for f in run_dir.iterdir():
                if f.suffix.lower() != ".json":
                    scraped[f.name] = f
    by_product: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for fname, meta in manifest.items():
        if not meta.get("untouched"):
            by_product[meta["product_id"]].append((fname, meta))
    return ground_truth, manifest, scraped, by_product


def _neighbour_transitions(gt: dict, true_label: str):
    """Yield (other_label, boxes) for the versions either side of `true_label`."""
    labels = gt["versions"]
    i = labels.index(true_label)
    for j in (i - 1, i + 1):
        if not 0 <= j < len(labels):
            continue
        other = labels[j]
        lo, hi = (true_label, other) if j > i else (other, true_label)
        boxes = [e["box"] for e in gt["transitions"].get(f"{lo}->{hi}", []) if e.get("box")]
        if boxes:
            yield other, boxes


def collect(corpus: Path, max_products: int, seed: int, per_product: int = 16) -> dict:
    """Pass 1 — per-pixel distributions, which set the two thresholds."""
    ground_truth, _manifest, scraped, by_product = _index_corpus(corpus)
    cfg = dict(DEFAULTS)
    rng = random.Random(seed)
    skus = sorted(ground_truth)[:max_products]

    unchanged_l, unchanged_c = [], []
    changed_l, changed_c = [], []
    per_image_l, per_image_c = [], []
    ref_cache: dict[tuple[str, str], np.ndarray] = {}

    def reference(sku: str, label: str) -> np.ndarray:
        key = (sku, label)
        if key not in ref_cache:
            ref_cache[key] = N.load_rgb(corpus / ground_truth[sku]["files"][label])
        return ref_cache[key]

    for sku in skus:
        gt = ground_truth[sku]
        variants = sorted(by_product[sku])
        rng.shuffle(variants)
        for fname, meta in variants[:per_product]:
            path = scraped.get(fname)
            if path is None:
                continue
            true_label = meta["true_version"]
            norm = N.normalize_scraped(path, cfg)

            # Unchanged: this variant against its own true reference. This is the
            # comparison the pipeline actually performs, so it is the right thing to
            # characterise — not two scraped variants against each other.
            s, r, _scale = N.prepare_pair(norm.rgb, reference(sku, true_label), cfg)
            lum, chrm = D.diff_channels(s, r, cfg["tolerance_radius"])
            unchanged_l.append(_subsample(lum, SAMPLE_PIXELS_PER_PAIR))
            unchanged_c.append(_subsample(chrm, SAMPLE_PIXELS_PER_PAIR))
            # Also keep each image's own upper tail. Pooling every pixel from every
            # image and taking one percentile lets the hardest size class set the
            # threshold for all of them: the 800px images carry several times the
            # residual of the 1500px ones, and a pooled 99.9th percentile lands
            # inside their noise rather than above the whole population's.
            per_image_l.append(float(np.percentile(lum, 99.9)))
            per_image_c.append(float(np.percentile(chrm, 99.9)))

            # Changed: same variant against a neighbouring version, sampled only
            # inside the boxes we know were edited.
            for other, boxes in _neighbour_transitions(gt, true_label):
                s2, r2, scale2 = N.prepare_pair(norm.rgb, reference(sku, other), cfg)
                l2, c2 = D.diff_channels(s2, r2, cfg["tolerance_radius"])
                bounds = (l2.shape[1], l2.shape[0])
                for box in boxes:
                    x, y, w, h = D.scale_box(tuple(box), scale2, bounds)
                    changed_l.append(l2[y:y + h, x:x + w].reshape(-1))
                    changed_c.append(c2[y:y + h, x:x + w].reshape(-1))

    def cat(xs):
        return np.concatenate(xs) if xs else np.zeros(1, np.float32)

    return {
        "corpus": corpus,
        "cfg": cfg,
        "skus": skus,
        "ground_truth": ground_truth,
        "scraped": scraped,
        "by_product": by_product,
        "per_image_luma": np.array(per_image_l),
        "per_image_chroma": np.array(per_image_c),
        "unchanged_luma": cat(unchanged_l),
        "unchanged_chroma": cat(unchanged_c),
        "changed_luma": cat(changed_l),
        "changed_chroma": cat(changed_c),
    }


def measure_fractions(data: dict, cfg: dict, per_product: int = 12) -> dict:
    """Pass 2 — at the chosen thresholds, how much of an image actually trips them.

    The per-pixel percentiles set the thresholds; these fractions set the decision
    rules, because a handful of hot pixels is normal and a changed region is not.
    """
    ground_truth = data["ground_truth"]
    rng = random.Random(7)

    unchanged_fracs, wrong_fracs = [], []
    unchanged_region, changed_region = [], []
    per_quality: dict = defaultdict(list)
    per_size: dict = defaultdict(list)
    ref_cache: dict[tuple[str, str], np.ndarray] = {}

    def reference(sku: str, label: str) -> np.ndarray:
        key = (sku, label)
        if key not in ref_cache:
            ref_cache[key] = N.load_rgb(data["corpus"] / ground_truth[sku]["files"][label])
        return ref_cache[key]

    for sku in data["skus"]:
        gt = ground_truth[sku]
        variants = sorted(data["by_product"][sku])
        rng.shuffle(variants)
        for fname, meta in variants[:per_product]:
            path = data["scraped"].get(fname)
            if path is None:
                continue
            true_label = meta["true_version"]
            norm = N.normalize_scraped(path, cfg)

            s, r, scale = N.prepare_pair(norm.rgb, reference(sku, true_label), cfg)
            score = D.diff_score(s, r, cfg)
            frac = D.changed_fraction(score, 1.0, cfg["morph_open"])
            unchanged_fracs.append(frac)
            per_quality[meta["quality"]].append(frac)
            per_size[meta["size"][0]].append(frac)

            for other, boxes in _neighbour_transitions(gt, true_label):
                s2, r2, scale2 = N.prepare_pair(norm.rgb, reference(sku, other), cfg)
                score2 = D.diff_score(s2, r2, cfg)
                wrong_fracs.append(D.changed_fraction(score2, 1.0, cfg["morph_open"]))
                for box in boxes:
                    b2 = D.scale_box(tuple(box), scale2, (score2.shape[1], score2.shape[0]))
                    changed_region.append(D.region_changed_fraction(
                        score2, b2, 1.0, cfg["region_morph_open"]))
                    b1 = D.scale_box(tuple(box), scale, (score.shape[1], score.shape[0]))
                    unchanged_region.append(D.region_changed_fraction(
                        score, b1, 1.0, cfg["region_morph_open"]))

    return {
        "unchanged_fracs": np.array(unchanged_fracs),
        "wrong_fracs": np.array(wrong_fracs),
        "unchanged_region": np.array(unchanged_region),
        "changed_region": np.array(changed_region),
        "per_quality": {k: np.array(v) for k, v in per_quality.items()},
        "per_size": {k: np.array(v) for k, v in per_size.items()},
    }


def plot(data: dict, cfg: dict, fracs: dict, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(11, 13))
    fig.patch.set_facecolor("white")
    blue, red = "#2f6fb3", "#c23b47"

    for ax, chan, thr in (
        (axes[0], "luma", cfg["luma_threshold"]),
        (axes[1], "chroma", cfg["chroma_threshold"]),
    ):
        u = data[f"unchanged_{chan}"]
        c = data[f"changed_{chan}"]
        bins = np.arange(0, 128, 1)
        ax.hist(u, bins=bins, density=True, alpha=0.75, color=blue,
                label=f"unchanged, re-encoded (n={u.size:,})")
        ax.hist(c, bins=bins, density=True, alpha=0.6, color=red,
                label=f"changed, inside edit region (n={c.size:,})")
        ax.axvline(thr, color="#111", linestyle="--", linewidth=1.6,
                   label=f"threshold = {thr:g} (99.9th pct of unchanged)")
        ax.set_yscale("log")
        ax.set_xlabel(f"per-pixel {chan} difference")
        ax.set_ylabel("density (log)")
        ax.set_title(f"{chan.capitalize()} noise floor vs. real artwork edits")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.25)

    ax = axes[2]
    ur, cr = fracs["unchanged_region"], fracs["changed_region"]
    top = max(0.05, float(cr.max()) if cr.size else 0.05)
    bins = np.linspace(0, top, 60)
    ax.hist(ur, bins=bins, alpha=0.75, color=blue, label="compared with the correct version")
    ax.hist(cr, bins=bins, alpha=0.6, color=red, label="compared with the wrong version")
    ax.set_yscale("log")
    ax.set_xlabel("fraction of a discriminating region over threshold")
    ax.set_ylabel("region comparisons (log)")
    ax.set_title("Region-level separation — the statistic version identification uses")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.calibrate")
    ap.add_argument("--corpus", default="./data/corpus")
    ap.add_argument("--max-products", type=int, default=12)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out-chart", default=str(REPO_ROOT / "calibration" / "noise_floor.png"))
    ap.add_argument("--out-config", default=None)
    args = ap.parse_args(argv)

    corpus = Path(args.corpus).resolve()
    print(f"Calibrating against {corpus} ...", flush=True)

    data = collect(corpus, args.max_products, args.seed)
    ul, uc = data["unchanged_luma"], data["unchanged_chroma"]
    cl, cc = data["changed_luma"], data["changed_chroma"]

    # The 99.9th percentile of the unchanged distribution, per spec. The per-image
    # figures below are reported alongside because they show something the pooled
    # number hides: the noise floor is strongly size-dependent, and the 800px class
    # carries several times the residual of the 1500px class.
    pil, pic = data["per_image_luma"], data["per_image_chroma"]
    luma_threshold = float(int(np.ceil(_pct(ul, 99.9))))
    chroma_threshold = float(int(np.ceil(_pct(uc, 99.9))))

    print(f"  sampled {ul.size:,} unchanged px, {cl.size:,} changed-region px "
          f"over {data['per_image_luma'].size} image pairs")
    print(f"  per-image p99.9 luma   p25/p50/p75/max : "
          f"{_pct(pil,25):.0f} / {_pct(pil,50):.0f} / {_pct(pil,75):.0f} / {_pct(pil,100):.0f}")
    print(f"  per-image p99.9 chroma p25/p50/p75/max : "
          f"{_pct(pic,25):.0f} / {_pct(pic,50):.0f} / {_pct(pic,75):.0f} / {_pct(pic,100):.0f}")
    print(f"  luma   unchanged p50/p99/p99.9 : {_pct(ul,50):5.1f} /{_pct(ul,99):6.1f} /{_pct(ul,99.9):6.1f}")
    print(f"  luma   changed   p50/p90/p99   : {_pct(cl,50):5.1f} /{_pct(cl,90):6.1f} /{_pct(cl,99):6.1f}")
    print(f"  chroma unchanged p50/p99/p99.9 : {_pct(uc,50):5.1f} /{_pct(uc,99):6.1f} /{_pct(uc,99.9):6.1f}")
    print(f"  chroma changed   p50/p90/p99   : {_pct(cc,50):5.1f} /{_pct(cc,90):6.1f} /{_pct(cc,99):6.1f}")

    cfg = dict(DEFAULTS)
    cfg["luma_threshold"] = luma_threshold
    cfg["chroma_threshold"] = chroma_threshold

    fracs = measure_fractions(data, cfg)
    u, w = fracs["unchanged_fracs"], fracs["wrong_fracs"]
    ur, cr = fracs["unchanged_region"], fracs["changed_region"]

    # An image counts as "clean" against a candidate if it trips less than this.
    # Derived from the worst correct-version image seen, with headroom.
    clean_fraction = float(max(u.max() * 3.0, 1e-5)) if u.size else DEFAULTS["clean_fraction"]

    ur_hi = _pct(ur, 99.0)
    cr_lo = _pct(cr, 5.0)
    region_frac = float(np.sqrt(max(ur_hi, 1e-4) * max(cr_lo, 1e-3)))
    region_frac = float(min(max(region_frac, 0.005), 0.5))

    # A bounding box is mostly unchanged background, so the changed distribution's
    # low percentiles describe that background, not the edit. Compare the noise
    # ceiling against the pixels that actually carry a change.
    luma_margin = _pct(cl, 99) - _pct(ul, 99.9)
    chroma_margin = _pct(cc, 99) - _pct(uc, 99.9)
    region_overlap = ur_hi >= cr_lo

    chart = Path(args.out_chart)
    plot(data, cfg, fracs, chart)

    out = {
        "luma_threshold": luma_threshold,
        "chroma_threshold": chroma_threshold,
        "clean_fraction": round(clean_fraction, 8),
        "region_changed_fraction": round(region_frac, 5),
        "calibrated": True,
        "calibration": {
            "corpus": str(corpus),
            "chart": str(chart),
            "unchanged_pixels": int(ul.size),
            "image_pairs": int(pil.size),
            "per_image_luma_p99_9": {"p50": round(_pct(pil, 50), 2),
                                     "p75": round(_pct(pil, 75), 2),
                                     "max": round(_pct(pil, 100), 2)},
            "per_image_chroma_p99_9": {"p50": round(_pct(pic, 50), 2),
                                       "p75": round(_pct(pic, 75), 2),
                                       "max": round(_pct(pic, 100), 2)},
            "changed_pixels": int(cl.size),
            "luma": {"unchanged_p99_9": round(_pct(ul, 99.9), 2),
                     "changed_p99": round(_pct(cl, 99), 2),
                     "separation_margin": round(luma_margin, 2)},
            "chroma": {"unchanged_p99_9": round(_pct(uc, 99.9), 2),
                       "changed_p99": round(_pct(cc, 99), 2),
                       "separation_margin": round(chroma_margin, 2)},
            "region_correct_p99": round(ur_hi, 6),
            "region_wrong_p05": round(cr_lo, 6),
            "region_wrong_p50": round(_pct(cr, 50), 6),
            "whole_image_correct_max": round(float(u.max()), 8) if u.size else None,
            "whole_image_wrong_median": round(float(np.median(w)), 8) if w.size else None,
            "by_jpeg_quality": {
                str(k): {"max_correct_fraction": round(float(v.max()), 8),
                         "median_correct_fraction": round(float(np.median(v)), 8)}
                for k, v in sorted(fracs["per_quality"].items()) if k is not None},
            "by_size": {
                str(k): {"max_correct_fraction": round(float(v.max()), 8),
                         "median_correct_fraction": round(float(np.median(v)), 8)}
                for k, v in sorted(fracs["per_size"].items())},
            "region_overlap_warning": bool(region_overlap),
        },
    }
    path = save_thresholds(out, Path(args.out_config) if args.out_config else None)

    print()
    print(f"  luma threshold   : {luma_threshold:g}   (separation margin {luma_margin:+.1f})")
    print(f"  chroma threshold : {chroma_threshold:g}   (separation margin {chroma_margin:+.1f})")
    print(f"  clean-image cutoff        : {clean_fraction:.2e} "
          f"(worst correct-version image {float(u.max()):.2e})")
    print(f"  region decision fraction  : {region_frac:.4f} "
          f"(correct p99 {ur_hi:.4f}, wrong p05 {cr_lo:.4f}, wrong p50 {_pct(cr,50):.4f})")
    print(f"  chart  -> {chart}")
    print(f"  config -> {path}")

    if region_overlap:
        print()
        print("!" * 78)
        print("WARNING: the correct-version and wrong-version region distributions overlap.")
        print("Some edits are indistinguishable from compression noise at the lower")
        print("quality/size combinations. Version identification falls back to ranking")
        print("candidates against each other, which tolerates this, but the affected")
        print("combinations are where the photograph track will be needed. See")
        print("RESULTS.md for the per-quality breakdown.")
        print("!" * 78)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
