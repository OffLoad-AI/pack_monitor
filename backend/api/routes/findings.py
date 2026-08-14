"""Finding detail, comparison images, and acknowledgement."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select

from db.models import Acknowledgement, ArtworkVersion, Finding, Product, ScrapedImage
from pipeline.references import THUMB_DIR

from ..deps import ack_map, decorate_regions, get_db, to_url
from ..schemas import AcknowledgeIn, FindingDetail, FindingImages

router = APIRouter(prefix="/api", tags=["findings"])


def _load(db, finding_id: int) -> Finding:
    f = db.get(Finding, finding_id)
    if f is None:
        raise HTTPException(404, f"No finding {finding_id}")
    return f


@router.get("/findings/{finding_id}", response_model=FindingDetail)
def finding_detail(finding_id: int, db=Depends(get_db)):
    f = _load(db, finding_id)
    img = db.get(ScrapedImage, f.scraped_image_id)
    acks = ack_map(db, [f.product_id], [f.current_version_id])
    regions, acknowledged = decorate_regions(f, acks)

    versions = db.scalars(
        select(ArtworkVersion).where(ArtworkVersion.product_id == f.product_id)
        .order_by(ArtworkVersion.id)).all()
    labels = {v.id: v.version_label for v in versions}

    chain: list[str] = []
    if f.matched_version_id and f.current_version_id:
        order = [v.id for v in versions]
        try:
            i, j = order.index(f.matched_version_id), order.index(f.current_version_id)
            chain = [labels[v] for v in order[i:j + 1]] if i <= j else []
        except ValueError:
            chain = []

    product = db.get(Product, f.product_id)
    return FindingDetail(
        id=f.id, run_id=f.run_id, product_id=f.product_id,
        product_name=product.name if product else None,
        verdict=f.verdict, severity=f.severity, match_method=f.match_method,
        confidence=f.confidence,
        matched_version=labels.get(f.matched_version_id),
        current_version=labels.get(f.current_version_id),
        matched_version_id=f.matched_version_id,
        current_version_id=f.current_version_id,
        region_count=len(regions), acknowledged=acknowledged,
        created_at=f.created_at, regions=regions,
        source_path=img.source_path if img else "",
        source_name=Path(img.source_path).name if img else None,
        thumb_url=to_url(img.source_path) if img else None,
        width=img.width if img else 0, height=img.height if img else 0,
        error=f.error, version_chain=chain,
    )


@router.get("/findings/{finding_id}/images", response_model=FindingImages)
def finding_images(finding_id: int, db=Depends(get_db)):
    f = _load(db, finding_id)
    img = db.get(ScrapedImage, f.scraped_image_id)
    matched = db.get(ArtworkVersion, f.matched_version_id) if f.matched_version_id else None
    current = db.get(ArtworkVersion, f.current_version_id) if f.current_version_id else None
    return FindingImages(
        scraped_url=to_url(img.source_path) if img else None,
        matched_url=to_url(matched.file_path) if matched else None,
        current_url=to_url(current.file_path) if current else None,
        diff_overlay_url=to_url(f.diff_map_path),
        scraped_size=[img.width, img.height] if img else None,
        matched_size=[matched.width, matched.height] if matched else None,
    )


@router.post("/findings/{finding_id}/acknowledge")
def acknowledge(finding_id: int, body: AcknowledgeIn, db=Depends(get_db)):
    f = _load(db, finding_id)
    regions = json.loads(f.regions_json or "[]")
    if not regions:
        raise HTTPException(400, "This finding has no changed regions to acknowledge")
    if f.current_version_id is None:
        raise HTTPException(400, "This finding has no reference version to scope to")
    if body.decision not in ("ACKNOWLEDGED", "ESCALATED"):
        raise HTTPException(400, "decision must be ACKNOWLEDGED or ESCALATED")

    created = 0
    for r in regions:
        sig = r.get("region_signature")
        if not sig:
            continue
        existing = db.scalar(
            select(Acknowledgement).where(
                Acknowledgement.product_id == f.product_id,
                Acknowledgement.region_signature == sig,
                Acknowledgement.reference_version_id == f.current_version_id))
        if existing:
            existing.decision = body.decision
            existing.note = body.note
            existing.created_by = body.created_by
        else:
            # Scoped to the reference version, so approving new artwork correctly
            # expires this sign-off and the finding comes back for review.
            db.add(Acknowledgement(
                product_id=f.product_id, region_signature=sig,
                reference_version_id=f.current_version_id,
                decision=body.decision, note=body.note, created_by=body.created_by))
            created += 1
    db.commit()
    return {"finding_id": finding_id, "decision": body.decision,
            "regions": len(regions), "created": created}


@router.delete("/findings/{finding_id}/acknowledge")
def unacknowledge(finding_id: int, db=Depends(get_db)):
    f = _load(db, finding_id)
    regions = json.loads(f.regions_json or "[]")
    sigs = [r.get("region_signature") for r in regions if r.get("region_signature")]
    if not sigs:
        return {"finding_id": finding_id, "removed": 0}
    result = db.execute(
        delete(Acknowledgement).where(
            Acknowledgement.product_id == f.product_id,
            Acknowledgement.region_signature.in_(sigs),
            Acknowledgement.reference_version_id == f.current_version_id))
    db.commit()
    return {"finding_id": finding_id, "removed": result.rowcount or 0}


@router.post("/findings/bulk-acknowledge")
def bulk_acknowledge(body: dict, db=Depends(get_db)):
    ids = body.get("finding_ids") or []
    decision = body.get("decision", "ACKNOWLEDGED")
    note = body.get("note", "")
    created_by = body.get("created_by", "reviewer")
    done = 0
    for fid in ids:
        try:
            acknowledge(fid, AcknowledgeIn(decision=decision, note=note,
                                           created_by=created_by), db)
            done += 1
        except HTTPException:
            continue
    return {"acknowledged": done, "requested": len(ids)}
