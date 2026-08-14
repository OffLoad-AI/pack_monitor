"""Product and artwork-version endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from db.models import ArtworkVersion, Finding, Product
from pipeline.references import THUMB_DIR

from ..deps import ack_map, decorate_regions, get_db, to_url
from ..schemas import ProductOut, VersionOut

router = APIRouter(prefix="/api", tags=["products"])


def _version_out(v: ArtworkVersion) -> VersionOut:
    return VersionOut(
        id=v.id, product_id=v.product_id, version_label=v.version_label,
        sha256=v.sha256, width=v.width, height=v.height,
        is_current=bool(v.is_current), approved_at=v.approved_at,
        image_url=to_url(v.file_path),
        thumb_url=to_url(THUMB_DIR / v.product_id / f"{v.version_label}.jpg"),
    )


@router.get("/products", response_model=list[ProductOut])
def list_products(db=Depends(get_db), q: str | None = None, limit: int = 500):
    stmt = select(Product).order_by(Product.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Product.name.ilike(like) | Product.id.ilike(like)
                          | Product.brand.ilike(like))
    products = db.scalars(stmt.limit(limit)).all()
    if not products:
        return []

    ids = [p.id for p in products]
    versions = db.scalars(
        select(ArtworkVersion).where(ArtworkVersion.product_id.in_(ids))).all()
    by_product: dict[str, list[ArtworkVersion]] = {}
    for v in versions:
        by_product.setdefault(v.product_id, []).append(v)

    latest_run = db.scalar(select(func.max(Finding.run_id)))
    last: dict[str, Finding] = {}
    open_counts: dict[str, int] = {}
    if latest_run:
        findings = db.scalars(
            select(Finding)
            .where(Finding.run_id == latest_run, Finding.product_id.in_(ids))
            .order_by(Finding.id)).all()
        acks = ack_map(db, [f.product_id for f in findings],
                       [f.current_version_id for f in findings])
        severity_rank = {"MATERIAL": 3, "UNCERTAIN": 2, "COSMETIC": 1, "NONE": 0}
        for f in findings:
            _regions, acknowledged = decorate_regions(f, acks)
            if f.verdict != "PASS" and not acknowledged:
                open_counts[f.product_id] = open_counts.get(f.product_id, 0) + 1
            prev = last.get(f.product_id)
            if prev is None or severity_rank.get(f.severity, 0) > severity_rank.get(prev.severity, 0):
                last[f.product_id] = f

    out = []
    for p in products:
        vs = sorted(by_product.get(p.id, []), key=lambda v: v.id)
        current = next((v for v in vs if v.is_current), vs[-1] if vs else None)
        f = last.get(p.id)
        out.append(ProductOut(
            id=p.id, name=p.name, brand=p.brand, version_count=len(vs),
            current_version=_version_out(current) if current else None,
            last_verdict=f.verdict if f else None,
            last_severity=f.severity if f else None,
            open_findings=open_counts.get(p.id, 0),
        ))
    return out


@router.get("/products/{product_id}")
def product_detail(product_id: str, db=Depends(get_db)):
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(404, f"No product {product_id}")

    versions = db.scalars(
        select(ArtworkVersion)
        .where(ArtworkVersion.product_id == product_id)
        .order_by(ArtworkVersion.id)).all()

    findings = db.scalars(
        select(Finding).where(Finding.product_id == product_id)
        .order_by(Finding.run_id.desc(), Finding.id.desc()).limit(300)).all()
    acks = ack_map(db, [product_id], [f.current_version_id for f in findings])
    labels = {v.id: v.version_label for v in versions}

    history = []
    for f in findings:
        regions, acknowledged = decorate_regions(f, acks)
        history.append({
            "id": f.id, "run_id": f.run_id, "verdict": f.verdict,
            "severity": f.severity, "match_method": f.match_method,
            "confidence": f.confidence,
            "matched_version": labels.get(f.matched_version_id),
            "current_version": labels.get(f.current_version_id),
            "region_count": len(regions), "acknowledged": acknowledged,
            "created_at": f.created_at,
        })

    return {
        "id": p.id, "name": p.name, "brand": p.brand, "created_at": p.created_at,
        "versions": [_version_out(v).model_dump() for v in versions],
        "findings": history,
    }


@router.get("/products/{product_id}/versions", response_model=list[VersionOut])
def product_versions(product_id: str, db=Depends(get_db)):
    versions = db.scalars(
        select(ArtworkVersion)
        .where(ArtworkVersion.product_id == product_id)
        .order_by(ArtworkVersion.id)).all()
    if not versions:
        raise HTTPException(404, f"No artwork registered for {product_id}")
    return [_version_out(v) for v in versions]
