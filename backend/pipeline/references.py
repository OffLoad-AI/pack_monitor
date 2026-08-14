"""Milestone 3 — offline reference processing (§8.1).

Registers every approved artwork version and works out, for each consecutive pair,
exactly which boxes distinguish them. Those boxes are what Stage 4 uses to tell two
versions apart when they are globally near-identical.

    python -m pipeline.references --corpus ./data/corpus
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image
from sqlalchemy import delete, select

from db.models import ArtworkVersion, DiscriminatingRegion, Product
from db.session import SessionLocal, init_db

from . import diff as D
from . import normalize as N
from .config import REPO_ROOT, load_thresholds

THUMB_DIR = REPO_ROOT / "data" / "thumbs"
THUMB_SIZE = (320, 320)

IOU_MATCH = 0.3


def make_thumbnail(src: Path, product_id: str, label: str) -> str:
    out_dir = THUMB_DIR / product_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{label}.jpg"
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail(THUMB_SIZE, Image.LANCZOS)
        im.save(out, "JPEG", quality=88)
    return str(out)


def process_corpus(corpus: Path, cfg: dict | None = None, verbose: bool = True) -> dict:
    cfg = cfg or load_thresholds()
    corpus = Path(corpus).resolve()
    ground_truth = json.loads((corpus / "ground_truth.json").read_text())
    products_meta = {}
    pmeta_path = corpus / "products.json"
    if pmeta_path.exists():
        products_meta = json.loads(pmeta_path.read_text())

    init_db()
    counts = {"products": 0, "versions": 0, "regions": 0, "mapped_regions": 0}

    with SessionLocal() as db:
        for sku in sorted(ground_truth):
            gt = ground_truth[sku]
            meta = products_meta.get(sku, {})

            product = db.get(Product, sku)
            if product is None:
                product = Product(id=sku, name=meta.get("name", sku),
                                  brand=meta.get("brand", "Unknown"))
                db.add(product)
            else:
                product.name = meta.get("name", product.name)
                product.brand = meta.get("brand", product.brand)

            # Discriminating regions are derived data and nothing points at them, so
            # they are rebuilt each time. Artwork versions are not: findings from
            # earlier runs reference them, and a version registry is append-mostly
            # by nature. Re-running therefore updates rows in place, keyed by label,
            # rather than deleting and recreating them.
            db.execute(delete(DiscriminatingRegion).where(
                DiscriminatingRegion.product_id == sku))

            existing = {v.version_label: v for v in db.scalars(
                select(ArtworkVersion).where(ArtworkVersion.product_id == sku)).all()}

            labels = gt["versions"]
            current_label = gt["current"]
            approved = gt.get("approved_at", {})

            version_rows: dict[str, ArtworkVersion] = {}
            images: dict[str, "object"] = {}

            for label in labels:
                path = (corpus / gt["files"][label]).resolve()
                rgb = N.load_rgb(path)
                images[label] = rgb
                row = existing.get(label)
                if row is None:
                    row = ArtworkVersion(product_id=sku, version_label=label)
                    db.add(row)
                row.file_path = str(path)
                row.sha256 = N.sha256_file(path)
                row.width = rgb.shape[1]
                row.height = rgb.shape[0]
                row.is_current = (label == current_label)
                row.approved_at = approved.get(label, "")
                version_rows[label] = row
                counts["versions"] += 1
                make_thumbnail(path, sku, label)

            # A label that has disappeared from the registry is retired, not erased —
            # findings that matched it must keep resolving.
            for label, row in existing.items():
                if label not in version_rows:
                    row.is_current = False

            db.flush()

            # --- consecutive-pair diffs ------------------------------------
            for a, b in zip(labels, labels[1:]):
                regions = D.reference_regions(images[a], images[b], cfg)
                edits = gt["transitions"].get(f"{a}->{b}", [])
                known = [e for e in edits if e.get("box")]

                for reg in regions:
                    # In production field_key/old/new come from OCR; for the MVP the
                    # corpus supplies them, matched by box overlap.
                    #
                    # IoU alone is not the right relation here. One logical edit
                    # often surfaces as several components — changing a nutrient
                    # updates both the per-100g and the per-serving column, hundreds
                    # of pixels apart — and each small component has poor IoU against
                    # the edit's overall extent. Containment catches those; IoU still
                    # catches the case where the detected box is the larger one.
                    best, best_score = None, 0.0
                    for e in known:
                        score = max(D.iou(reg, e["box"]), D.containment(reg, e["box"]))
                        if score > best_score:
                            best, best_score = e, score

                    matched = best if best_score > IOU_MATCH else None
                    if matched:
                        counts["mapped_regions"] += 1

                    db.add(DiscriminatingRegion(
                        product_id=sku,
                        from_version_id=version_rows[a].id,
                        to_version_id=version_rows[b].id,
                        x=reg["x"], y=reg["y"], w=reg["w"], h=reg["h"],
                        area_fraction=reg["area_fraction"],
                        field_key=matched["field"] if matched else None,
                        old_value=matched["old"] if matched else None,
                        new_value=matched["new"] if matched else None,
                        edit_type=matched["type"] if matched else None,
                        severity=matched["severity"] if matched else "UNKNOWN",
                    ))
                    counts["regions"] += 1

            counts["products"] += 1
            if verbose and counts["products"] % 10 == 0:
                print(f"  processed {counts['products']} products", flush=True)

        db.commit()

    return counts


def reset_history() -> dict:
    """Drop all run history so the registry can be rebuilt from scratch.

    Used when the corpus itself is regenerated, which invalidates every stored
    verdict. Acknowledgements go too: they are scoped to reference versions that no
    longer exist.
    """
    from db.models import Acknowledgement, Finding, Run, ScrapedImage

    init_db()
    removed = {}
    with SessionLocal() as db:
        for model in (Finding, ScrapedImage, Run, Acknowledgement):
            removed[model.__tablename__] = db.execute(delete(model)).rowcount or 0
        db.commit()
    return removed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pipeline.references")
    ap.add_argument("--corpus", default="./data/corpus")
    ap.add_argument("--reset", action="store_true",
                    help="delete all runs, findings and acknowledgements first "
                         "(needed after regenerating the corpus)")
    args = ap.parse_args(argv)

    if args.reset:
        print(f"reset: {reset_history()}")

    counts = process_corpus(Path(args.corpus))
    print(json.dumps(counts, indent=2))
    unmapped = counts["regions"] - counts["mapped_regions"]
    if unmapped:
        print(f"note: {unmapped} discriminating regions had no matching ground-truth "
              f"edit and are recorded with severity UNKNOWN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
