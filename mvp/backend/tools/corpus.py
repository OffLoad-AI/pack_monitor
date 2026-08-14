"""Pairwise test corpus with exact ground truth.

    python -m tools.corpus pairs --out ./data/pairs --count 200

The version-identification build's corpus emits *version chains* — v1, v2, v3 and
a pile of marketplace variants of each — because the question there is "which of
these is the listing serving?". Here the question is asked one pair at a time, so
the corpus emits **pairs**: a reference, a marketplace image, and what the answer
should be.

Nine case classes, chosen to cover the ways the answer can be right and the ways
it can be wrong. `PHOTOGRAPHED` is the one that matters most — it is the case the
other build cannot handle at all and this build exists to prove out — so it is
constructed by applying a **known** homography, which lets the recovered matrix be
checked against ground truth directly rather than only through its consequences.

Ground truth is exact by construction: every edit box is measured from the actual
pixel difference between two renders (`artwork.diff_box`), never recorded by
bookkeeping, so the labels cannot drift away from the pixels.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageCms, ImageFilter

from . import artwork
from .artwork import CANVAS, apply_edit, diff_box, make_state, render

# The verdict each class should produce, and the severity it should carry.
CASE_CLASSES = {
    "IDENTICAL":     {"verdict": "IDENTICAL", "weight": 8},
    "REENCODED":     {"verdict": "MATCH", "weight": 22},
    "NUMERIC_DRIFT": {"verdict": "DIFFERENT", "weight": 20},
    "CLAIM_REMOVED": {"verdict": "DIFFERENT", "weight": 10},
    "CERT_REMOVED":  {"verdict": "DIFFERENT", "weight": 8},
    "PALETTE_SHIFT": {"verdict": "MATCH_WITH_COSMETIC_DIFFERENCES", "weight": 8},
    "PHOTOGRAPHED":  {"verdict": "MATCH", "weight": 16},
    "WRONG_PRODUCT": {"verdict": "DIFFERENT", "weight": 5},
    "UNRELATED":     {"verdict": "CANNOT_COMPARE", "weight": 3},
}

# Classes where more than one verdict is defensible, and pretending otherwise
# would make the accuracy number a fiction. A `WRONG_PRODUCT` pair that fails to
# register is *correctly* refused; one that registers on the shared layout and
# then finds every value different is *also* correct.
ACCEPTABLE = {
    "WRONG_PRODUCT": {"DIFFERENT", "CANNOT_COMPARE"},
    "UNRELATED": {"CANNOT_COMPARE"},
    "PALETTE_SHIFT": {"MATCH_WITH_COSMETIC_DIFFERENCES"},
    # The spec is internally inconsistent here, and the inconsistency is worth
    # naming rather than resolving silently. Its corpus table expects
    # `CERT_REMOVED` to produce `DIFFERENT` "via VISUAL_ONLY"; its verdict table
    # says a comparison whose only differences are `VISUAL_ONLY` produces
    # `NEEDS_REVIEW`. Both cannot hold. The verdict table governs, because a
    # removed mark genuinely cannot be confirmed without a person — there is no
    # text to read and nothing to rank against. So the pipeline answers
    # `NEEDS_REVIEW` and both verdicts count as correct here: what the class
    # actually tests is that a change with no text is *found* and attributed,
    # rather than discarded.
    "CERT_REMOVED": {"NEEDS_REVIEW", "DIFFERENT"},
}

PAD_FRACTION = artwork.PAD_FRACTION
JPEG_QUALITIES = artwork.JPEG_QUALITIES
SIZES = artwork.SIZES


# --------------------------------------------------------------------------
# Marketplace transforms
# --------------------------------------------------------------------------


def _srgb_profile_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def pad_square(img: Image.Image, mode: str) -> Image.Image:
    """Marketplaces re-frame artwork onto their own canvas, adding uniform padding.

    The pad fraction puts the boundary at a **non-integer pixel** after
    downscaling — pad 1500 to 1800, resize to 800, and the true edge lands at
    66.67. That is not an accident of the generator; it is the realistic case.
    """
    w, h = img.size
    pad = int(round(w * PAD_FRACTION / (1 - 2 * PAD_FRACTION)))
    nw, nh = w + 2 * pad, h + 2 * pad
    if mode == "square_pad_transparent":
        canvas = Image.new("RGBA", (nw, nh), (255, 255, 255, 0))
        canvas.paste(img.convert("RGBA"), (pad, pad))
    else:
        canvas = Image.new("RGB", (nw, nh), (255, 255, 255))
        canvas.paste(img, (pad, pad))
    return canvas


def emit_reencoded(img: Image.Image, out: Path, quality: int, size, padding, fmt: str,
                   icc: bool = False) -> None:
    """What a marketplace CDN does to a file it was given."""
    work = pad_square(img, padding) if padding else img
    work = work.resize(size, Image.LANCZOS)

    kwargs: dict[str, Any] = {"quality": quality}
    if icc:
        kwargs["icc_profile"] = _srgb_profile_bytes()

    if fmt == "jpeg":
        if work.mode != "RGB":
            bg = Image.new("RGB", work.size, (255, 255, 255))
            bg.paste(work, mask=work.split()[-1])
            work = bg
        kwargs["subsampling"] = "4:2:0"
        work.save(out, "JPEG", **kwargs)
    else:
        work.save(out, "WEBP", **kwargs)


def photograph_homography(rng: random.Random, size: int = CANVAS) -> np.ndarray:
    """A plausible hand-held perspective, as an exact 3x3 matrix.

    Kept mild — a few percent of corner displacement, a small rotation and a
    small scale — because a phone photo of a pack front is taken square-on by
    someone trying to photograph the pack front. The point of storing the matrix
    is that the recovered one can be compared against it directly.
    """
    s = size
    jitter = s * 0.045
    src = np.float32([[0, 0], [s, 0], [s, s], [0, s]])
    dst = np.float32([[rng.uniform(0, jitter), rng.uniform(0, jitter)],
                      [s - rng.uniform(0, jitter), rng.uniform(0, jitter)],
                      [s - rng.uniform(0, jitter), s - rng.uniform(0, jitter)],
                      [rng.uniform(0, jitter), s - rng.uniform(0, jitter)]])
    import cv2

    return cv2.getPerspectiveTransform(src, dst)


def emit_photographed(img: Image.Image, out: Path, H: np.ndarray,
                      rng: random.Random, quality: int = 82) -> None:
    """Perspective warp, lighting gradient, glare, blur, sensor noise, JPEG.

    Synthetic warps do not reproduce real specular highlights on foil or real
    camera noise — that is what the real-photograph supplement in the README is
    for. What this *does* reproduce faithfully is the geometry, which is the part
    with an exact ground truth attached.
    """
    import cv2

    rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]
    warped = cv2.warpPerspective(rgb, H, (w, h), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)

    # Lighting gradient: brighter toward one corner, as a window or a lamp does.
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ang = rng.uniform(0, 2 * np.pi)
    ramp = (np.cos(ang) * xx / w + np.sin(ang) * yy / h)
    gain = 1.0 + rng.uniform(0.10, 0.28) * (ramp - ramp.mean())
    lit = np.clip(warped.astype(np.float32) * gain[:, :, None], 0, 255)

    # One soft specular blob — the thing that actually destroys OCR on foil.
    gx, gy = rng.uniform(0.15, 0.85) * w, rng.uniform(0.15, 0.85) * h
    radius = rng.uniform(0.10, 0.20) * max(w, h)
    glare = np.exp(-(((xx - gx) ** 2 + (yy - gy) ** 2) / (2 * radius ** 2)))
    lit = np.clip(lit + (glare * rng.uniform(30, 70))[:, :, None], 0, 255)

    out_img = Image.fromarray(lit.astype(np.uint8))
    out_img = out_img.filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 1.3)))

    arr = np.asarray(out_img).astype(np.float32)
    arr += rng.uniform(1.5, 4.0) * np.random.default_rng(
        rng.randrange(1 << 30)).standard_normal(arr.shape)
    out_img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    out_img.save(out, "JPEG", quality=quality, subsampling="4:2:0")


def emit_noise(out: Path, rng: random.Random, size: int = 1000) -> None:
    """Structured noise, not white noise.

    Pure per-pixel noise has no keypoints at all, which makes refusing it trivial
    and the test worthless. Smoothed noise has plenty of blobby keypoints that
    match nothing consistently — which is the honest hard case.
    """
    g = np.random.default_rng(rng.randrange(1 << 30))
    arr = g.integers(0, 255, (size // 8, size // 8, 3), dtype=np.uint8)
    img = Image.fromarray(arr).resize((size, size), Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(1.5))
    img.save(out, "JPEG", quality=80)


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------


@dataclass
class Case:
    name: str
    case_class: str
    reference: str          # path relative to the corpus root
    marketplace: str
    expected_verdict: str
    acceptable_verdicts: list[str]
    expected_severity: str
    edits: list[dict]
    transform: dict
    homography: list[list[float]] | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "case_class": self.case_class,
            "reference": self.reference,
            "marketplace": self.marketplace,
            "expected_verdict": self.expected_verdict,
            "acceptable_verdicts": self.acceptable_verdicts,
            "expected_severity": self.expected_severity,
            "edits": self.edits,
            "transform": self.transform,
            "homography": self.homography,
        }


def _weighted_plan(count: int) -> list[str]:
    """Deterministic, stratified class assignment.

    Walked as a repeating stratified sequence rather than sampled, so that a
    corpus of 40 and a corpus of 200 have the same class proportions and the
    per-class accuracy numbers stay comparable between runs of different sizes.
    """
    total = sum(c["weight"] for c in CASE_CLASSES.values())
    plan: list[str] = []
    for name, spec in CASE_CLASSES.items():
        n = max(1, round(count * spec["weight"] / total))
        plan.extend([name] * n)
    plan = plan[:count] if len(plan) >= count else plan + [
        "REENCODED"] * (count - len(plan))
    plan.sort(key=lambda n: list(CASE_CLASSES).index(n))
    # Interleave so a partial run still spans every class.
    buckets: dict[str, list[str]] = {}
    for n in plan:
        buckets.setdefault(n, []).append(n)
    out: list[str] = []
    while any(buckets.values()):
        for key in list(buckets):
            if buckets[key]:
                out.append(buckets[key].pop())
    return out[:count]


def _edit_case(state, edit_type: str, rng: random.Random):
    """Apply one edit and measure its box against the render just before it."""
    result = apply_edit(state, edit_type, rng)
    if result is None:
        return None
    new_state, record = result
    box = diff_box(render(state), render(new_state))
    if box is None:
        return None
    record["box"] = box
    return new_state, record


SEVERITY_BY_CLASS = {
    "IDENTICAL": "NONE",
    "REENCODED": "NONE",
    "NUMERIC_DRIFT": "MATERIAL",
    "CLAIM_REMOVED": "MATERIAL",
    "CERT_REMOVED": "UNCERTAIN",   # no text to read; VISUAL_ONLY by construction
    "PALETTE_SHIFT": "COSMETIC",
    "PHOTOGRAPHED": "NONE",
    "WRONG_PRODUCT": "MATERIAL",
    "UNRELATED": "NONE",
}


def build_case(index: int, case_class: str, out_dir: Path, seed: int,
               rank: int = 0) -> Case | None:
    rng = random.Random(f"{seed}:{index}:{case_class}")
    images = out_dir / "images"

    state = make_state(f"SKU{index:04d}", rng, index=index)
    ref_img = render(state)
    name = f"{index:04d}_{case_class}"
    ref_path = images / f"ref__{name}.png"
    ref_img.save(ref_path, "PNG", optimize=False)

    # Quality and size are **stratified within the class**, not sampled. They are
    # the two axes accuracy is reported against, and they are also the two that
    # decide whether a one-digit edit is detectable at all. Sampling them lets a
    # small corpus draw an entire class at the hard end and report a rate of zero
    # that says nothing about the method. The other build hit exactly this: at 12
    # variants per version the 800px size was never generated, which hid the
    # system's real weak point.
    quality = JPEG_QUALITIES[rank % len(JPEG_QUALITIES)]
    size = SIZES[(rank // len(JPEG_QUALITIES)) % len(SIZES)]
    padding = rng.choice([None, "square_pad_white", "square_pad_transparent"])
    fmt = rng.choice(["jpeg", "webp"])
    transform = {"quality": quality, "size": list(size), "padding": padding,
                 "format": fmt}
    edits: list[dict] = []
    homography = None

    if case_class == "IDENTICAL":
        mkt_path = images / f"mkt__{name}.png"
        shutil.copyfile(ref_path, mkt_path)
        transform = {"quality": None, "size": [CANVAS, CANVAS], "padding": None,
                     "format": "png", "byte_copy": True}

    elif case_class == "REENCODED":
        mkt_path = images / f"mkt__{name}.{'jpg' if fmt == 'jpeg' else 'webp'}"
        emit_reencoded(ref_img, mkt_path, quality, size, padding, fmt,
                       icc=rng.random() < 0.3)

    elif case_class in ("NUMERIC_DRIFT", "CLAIM_REMOVED", "CERT_REMOVED",
                        "PALETTE_SHIFT"):
        result = _edit_case(state, case_class, rng)
        if result is None:
            return None
        edited_state, record = result
        edits.append(record)
        mkt_path = images / f"mkt__{name}.{'jpg' if fmt == 'jpeg' else 'webp'}"
        emit_reencoded(render(edited_state), mkt_path, quality, size, padding, fmt)

    elif case_class == "PHOTOGRAPHED":
        # Half the photographed pairs also carry a real edit, so the class tests
        # both "registration survives a camera" and "a change is still found
        # through one".
        edited_state = state
        if rng.random() < 0.5:
            result = _edit_case(state, "NUMERIC_DRIFT", rng)
            if result is not None:
                edited_state, record = result
                edits.append(record)
        H = photograph_homography(rng)
        homography = [[float(v) for v in row] for row in H]
        mkt_path = images / f"mkt__{name}.jpg"
        emit_photographed(render(edited_state), mkt_path, H, rng)
        transform = {"quality": 82, "size": [CANVAS, CANVAS], "padding": None,
                     "format": "jpeg", "photographed": True}

    elif case_class == "WRONG_PRODUCT":
        other = make_state(f"SKU{index:04d}X", random.Random(f"{seed}:other:{index}"),
                           index=index + 977)
        mkt_path = images / f"mkt__{name}.jpg"
        emit_reencoded(render(other), mkt_path, quality, size, padding, "jpeg")

    elif case_class == "UNRELATED":
        mkt_path = images / f"mkt__{name}.jpg"
        emit_noise(mkt_path, rng)
        transform = {"quality": 80, "size": [1000, 1000], "padding": None,
                     "format": "jpeg", "noise": True}

    else:  # pragma: no cover - the plan only ever emits known classes
        raise ValueError(f"unknown case class {case_class!r}")

    spec = CASE_CLASSES[case_class]
    expected = spec["verdict"]
    # A photographed pair that also carries an edit expects DIFFERENT, per the
    # underlying edit rather than per the class.
    severity = SEVERITY_BY_CLASS[case_class]
    if case_class == "PHOTOGRAPHED" and edits:
        expected = "DIFFERENT"
        severity = "MATERIAL"

    acceptable = sorted(ACCEPTABLE.get(case_class, {expected}))
    return Case(
        name=name, case_class=case_class,
        reference=str(ref_path.relative_to(out_dir)).replace("\\", "/"),
        marketplace=str(mkt_path.relative_to(out_dir)).replace("\\", "/"),
        expected_verdict=expected, acceptable_verdicts=acceptable,
        expected_severity=severity, edits=edits, transform=transform,
        homography=homography)


def generate_pairs(out_dir: Path, count: int, seed: int) -> dict:
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "images").mkdir(parents=True)

    plan = _weighted_plan(count)
    cases: list[Case] = []
    seen: dict[str, int] = {}
    for i, case_class in enumerate(plan, start=1):
        rank = seen.get(case_class, 0)
        seen[case_class] = rank + 1
        case = build_case(i, case_class, out_dir, seed, rank=rank)
        if case is None:
            # The edit was not applicable to this randomly-generated pack (no
            # certification marks to remove, say). Fall back rather than skip, so
            # the requested count is always what is produced.
            case = build_case(i, "REENCODED", out_dir, seed, rank=rank)
        if case is not None:
            cases.append(case)
        if i % 20 == 0 or i == len(plan):
            print(f"  generated {i}/{len(plan)} pairs", flush=True)

    ground_truth = {c.name: c.as_dict() for c in cases}
    (out_dir / "ground_truth.json").write_text(
        json.dumps(ground_truth, indent=2, sort_keys=True))

    by_class: dict[str, int] = {}
    for c in cases:
        by_class[c.case_class] = by_class.get(c.case_class, 0) + 1

    summary = {"pairs": len(cases), "seed": seed, "by_class": by_class}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.corpus")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pairs", help="generate a pairwise corpus with ground truth")
    p.add_argument("--out", default="./data/pairs")
    p.add_argument("--count", type=int, default=200)
    p.add_argument("--seed", type=int, default=20260201)

    args = ap.parse_args(argv)
    if args.cmd == "pairs":
        summary = generate_pairs(Path(args.out), args.count, args.seed)
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
