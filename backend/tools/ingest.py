"""Build a reference registry from real artwork files.

`pipeline.references` reads the corpus manifest format — `ground_truth.json` plus
an optional `products.json`. That format carries two separate things: the version
chain (which the pipeline genuinely needs) and the per-edit field metadata (which
in production comes from OCR, and which nothing requires). This writes the first
and leaves the second empty, so real artwork can be registered without inventing
labels for it.

Expected input layout:

    <dir>/
      references/
        SKU001/  v1.png  v2.png  v3.png
        SKU002/  2024-03.png  2025-01.png

Version order is the chain order, and the last one is the approved version.
Labels sort naturally (v2 before v10), so numbered or dated filenames both work.
Override either with `versions.json`; see --write-template.

    python -m tools.ingest --dir ../data/real
    python -m tools.ingest --dir ../data/real --write-template
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def natural_key(label: str) -> list:
    """Sort v2 before v10, and 2024-03 before 2025-01."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", label)]


def discover_versions(ref_root: Path) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for sku_dir in sorted(p for p in ref_root.iterdir() if p.is_dir()):
        files = [f for f in sku_dir.iterdir()
                 if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
        if not files:
            continue
        out[sku_dir.name] = sorted(files, key=lambda f: natural_key(f.stem))
    return out


def build(root: Path) -> tuple[dict, dict]:
    root = root.resolve()
    ref_root = root / "references"
    if not ref_root.is_dir():
        raise SystemExit(f"no references/ directory under {root}")

    found = discover_versions(ref_root)
    if not found:
        raise SystemExit(f"no artwork found under {ref_root}")

    overrides = {}
    override_path = root / "versions.json"
    if override_path.exists():
        overrides = json.loads(override_path.read_text())

    ground_truth: dict[str, dict] = {}
    products: dict[str, dict] = {}

    for sku, files in found.items():
        ov = overrides.get(sku, {})
        by_label = {f.stem: f for f in files}

        labels = ov.get("versions") or [f.stem for f in files]
        missing = [lab for lab in labels if lab not in by_label]
        if missing:
            raise SystemExit(
                f"{sku}: versions.json lists {missing}, which have no file in "
                f"{ref_root / sku}")

        current = ov.get("current", labels[-1])
        if current not in labels:
            raise SystemExit(f"{sku}: current version {current!r} is not in {labels}")

        approved = ov.get("approved_at", {})
        for lab in labels:
            if lab not in approved:
                ts = by_label[lab].stat().st_mtime
                approved[lab] = datetime.fromtimestamp(
                    ts, tz=timezone.utc).isoformat()

        ground_truth[sku] = {
            "versions": labels,
            "current": current,
            "files": {lab: str(by_label[lab].relative_to(root)) for lab in labels},
            "approved_at": approved,
            # Field metadata is OCR's job in production. Regions still get detected
            # and diffed; they are recorded with severity UNKNOWN until something
            # fills this in.
            "transitions": ov.get("transitions", {}),
        }
        products[sku] = {
            "name": ov.get("name", sku),
            "brand": ov.get("brand", "Unknown"),
        }

    return ground_truth, products


def write_template(root: Path, ground_truth: dict) -> Path:
    """Emit a versions.json seeded with what was inferred, for hand-editing."""
    tmpl = {
        sku: {
            "name": sku,
            "brand": "Unknown",
            "versions": gt["versions"],
            "current": gt["current"],
            "approved_at": gt["approved_at"],
        }
        for sku, gt in ground_truth.items()
    }
    out = root / "versions.template.json"
    out.write_text(json.dumps(tmpl, indent=2, sort_keys=True) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.ingest")
    ap.add_argument("--dir", required=True,
                    help="directory containing references/<SKU>/<label>.<ext>")
    ap.add_argument("--write-template", action="store_true",
                    help="also write versions.template.json for hand-editing "
                         "labels, order, approval dates, names and brands")
    args = ap.parse_args(argv)

    root = Path(args.dir).resolve()
    ground_truth, products = build(root)

    (root / "ground_truth.json").write_text(
        json.dumps(ground_truth, indent=2, sort_keys=True) + "\n")
    (root / "products.json").write_text(
        json.dumps(products, indent=2, sort_keys=True) + "\n")

    n_versions = sum(len(g["versions"]) for g in ground_truth.values())
    print(f"wrote {root / 'ground_truth.json'}")
    print(f"  {len(ground_truth)} products, {n_versions} artwork versions")

    single = [s for s, g in ground_truth.items() if len(g["versions"]) == 1]
    if single:
        print(f"note: {len(single)} product(s) have only one version, so there are "
              f"no discriminating regions for them — every listing will resolve by "
              f"hash or whole-image difference, or refuse")

    if args.write_template:
        print(f"wrote {write_template(root, ground_truth)}  "
              f"(rename to versions.json to apply)")

    print(f"\nnext: python -m pipeline.references --corpus {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
