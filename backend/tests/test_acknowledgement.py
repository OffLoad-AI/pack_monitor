"""Acknowledgement lifecycle and the run cache (§11)."""

from __future__ import annotations

import json

import numpy as np
from PIL import Image
from sqlalchemy import select

from db.models import (Acknowledgement, ArtworkVersion, DiscriminatingRegion,
                       Finding, Run)
from db.session import SessionLocal
from pipeline import diff as D
from pipeline import normalize as N
from pipeline.config import load_thresholds

DEFAULT_QUEUE = {"verdict": "STALE_VERSION", "severity": "MATERIAL"}


def _default_queue(run_id: int) -> list[Finding]:
    """The review queue as the UI shows it by default: unacknowledged material
    staleness."""
    from api.deps import ack_map, decorate_regions

    with SessionLocal() as db:
        findings = db.scalars(
            select(Finding).where(
                Finding.run_id == run_id,
                Finding.verdict == DEFAULT_QUEUE["verdict"],
                Finding.severity == DEFAULT_QUEUE["severity"])).all()
        acks = ack_map(db, [f.product_id for f in findings],
                       [f.current_version_id for f in findings])
        return [f for f in findings if not decorate_regions(f, acks)[1]]


def _acknowledge(finding_id: int) -> int:
    with SessionLocal() as db:
        f = db.get(Finding, finding_id)
        regions = json.loads(f.regions_json or "[]")
        created = 0
        for r in regions:
            sig = r.get("region_signature")
            if not sig:
                continue
            db.add(Acknowledgement(
                product_id=f.product_id, region_signature=sig,
                reference_version_id=f.current_version_id,
                decision="ACKNOWLEDGED", note="reviewed in test",
                created_by="tester"))
            created += 1
        db.commit()
    return created


def test_acknowledgement_suppression(fresh_env):
    """An acknowledged finding does not come back in the default queue."""
    run1 = fresh_env.run(workers=4)
    queue = _default_queue(run1)
    assert queue, "expected material stale findings to review"

    target = queue[0]
    product_id = target.product_id
    assert _acknowledge(target.id) > 0

    assert target.id not in {f.id for f in _default_queue(run1)}, (
        "acknowledged finding still in the queue for the same run")

    run2 = fresh_env.run(workers=4, use_cache=False)
    still_open = [f for f in _default_queue(run2) if f.product_id == product_id]
    assert not still_open, (
        f"{len(still_open)} findings for {product_id} resurfaced after "
        f"acknowledgement despite unchanged artwork")


def test_acknowledgement_expires_on_new_version(fresh_env):
    """Approving new artwork expires old sign-offs and findings come back.

    Acknowledgements are scoped to the reference version they were made against,
    so a reviewer's "this is fine" cannot silently carry over to artwork they never
    looked at.
    """
    run1 = fresh_env.run(workers=4)
    queue = _default_queue(run1)
    assert queue

    target = queue[0]
    product_id = target.product_id
    _acknowledge(target.id)
    assert not [f for f in _default_queue(run1) if f.id == target.id]

    # Approve a genuinely new artwork version for that product.
    cfg = load_thresholds()
    with SessionLocal() as db:
        versions = db.scalars(
            select(ArtworkVersion)
            .where(ArtworkVersion.product_id == product_id)
            .order_by(ArtworkVersion.id)).all()
        current = next(v for v in versions if v.is_current)

        img = Image.open(current.file_path).convert("RGB")
        arr = np.array(img)
        # A material-looking edit: overwrite a slab of the nutrition panel.
        arr[900:940, 700:1000] = (255, 0, 0)
        new_path = fresh_env.db_path.parent / f"{product_id}_next.png"
        Image.fromarray(arr).save(new_path)

        new_version = ArtworkVersion(
            product_id=product_id, version_label="v99",
            file_path=str(new_path), sha256=N.sha256_file(new_path),
            width=arr.shape[1], height=arr.shape[0], is_current=True,
            approved_at="2026-07-01T00:00:00+00:00")
        current.is_current = False
        db.add(new_version)
        db.flush()

        for region in D.reference_regions(N.load_rgb(current.file_path), arr, cfg):
            db.add(DiscriminatingRegion(
                product_id=product_id, from_version_id=current.id,
                to_version_id=new_version.id,
                x=region["x"], y=region["y"], w=region["w"], h=region["h"],
                area_fraction=region["area_fraction"],
                field_key="nutrition_panel", old_value="approved",
                new_value="revised", edit_type="NUMERIC_DRIFT",
                severity="MATERIAL"))
        db.commit()

    run2 = fresh_env.run(workers=4)
    resurfaced = [f for f in _default_queue(run2) if f.product_id == product_id]
    assert resurfaced, (
        f"no findings for {product_id} resurfaced after new artwork was approved; "
        f"acknowledgements did not expire")
    print(f"\n  {len(resurfaced)} findings resurfaced for review after v99 approved")


def test_cache_hit_rate(fresh_env):
    """Re-running identical input serves every image from the cache."""
    fresh_env.run(workers=4)
    second = fresh_env.run(workers=4)

    with SessionLocal() as db:
        run = db.get(Run, second)
    assert run.images_total > 0
    assert run.images_cached == run.images_total, (
        f"only {run.images_cached}/{run.images_total} images came from cache")
    print(f"\n  {run.images_cached}/{run.images_total} images cached on re-run")


def test_cache_is_bypassed_when_artwork_changes(fresh_env):
    """A new approved version must force re-evaluation of unchanged files.

    The bytes on the listing did not change, but the question did: the same image
    that was compliant last month is stale once new artwork is approved.
    """
    fresh_env.run(workers=4)

    with SessionLocal() as db:
        product_id = db.scalar(select(ArtworkVersion.product_id).limit(1))
        current = db.scalar(
            select(ArtworkVersion).where(ArtworkVersion.product_id == product_id,
                                         ArtworkVersion.is_current.is_(True)))
        arr = np.array(Image.open(current.file_path).convert("RGB"))
        arr[400:460, 200:600] = (0, 0, 255)
        new_path = fresh_env.db_path.parent / f"{product_id}_bump.png"
        Image.fromarray(arr).save(new_path)
        current.is_current = False
        db.add(ArtworkVersion(
            product_id=product_id, version_label="v98", file_path=str(new_path),
            sha256=N.sha256_file(new_path), width=arr.shape[1], height=arr.shape[0],
            is_current=True, approved_at="2026-07-01T00:00:00+00:00"))
        db.commit()

    third = fresh_env.run(workers=4)
    with SessionLocal() as db:
        run = db.get(Run, third)
        reprocessed = db.scalar(
            select(Finding).where(Finding.run_id == third,
                                  Finding.product_id == product_id))
    assert run.images_cached < run.images_total, (
        "images were served from cache even though the approved artwork changed")
    assert reprocessed is not None
