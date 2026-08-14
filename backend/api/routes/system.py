"""Thresholds, calibration, and dashboard aggregates."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from db.models import ArtworkVersion, Finding, Product, Run
from pipeline.config import CONFIG_PATH, DEFAULTS, load_thresholds, save_thresholds

from ..deps import ack_map, decorate_regions, get_db, to_url
from ..schemas import ThresholdsOut

router = APIRouter(prefix="/api", tags=["system"])

CALIBRATION_CHART = Path(CONFIG_PATH).resolve().parents[1] / "calibration" / "noise_floor.png"

# Only these are safe to edit by hand; the rest are structural.
EDITABLE = {
    "luma_threshold", "chroma_threshold", "clean_fraction",
    "region_changed_fraction", "region_margin_ratio", "region_signal_cap",
    "tolerance_radius", "morph_open", "region_morph_open", "morph_close",
    "min_region_area_fraction", "reference_luma_threshold",
    "reference_chroma_threshold", "border_uniform_tolerance",
}


@router.get("/config/thresholds", response_model=ThresholdsOut)
def get_thresholds():
    cfg = load_thresholds()
    calibration = cfg.pop("calibration", None)
    return ThresholdsOut(
        values=cfg, calibration=calibration,
        chart_url=to_url(CALIBRATION_CHART) if CALIBRATION_CHART.exists() else None)


@router.put("/config/thresholds", response_model=ThresholdsOut)
def put_thresholds(body: dict):
    """Update thresholds. Completed runs are unaffected — each run froze its own
    configuration at start, so history cannot be rewritten by a later edit."""
    stored = {}
    if CONFIG_PATH.exists():
        stored = json.loads(CONFIG_PATH.read_text())

    updates = body.get("values", body)
    unknown = set(updates) - EDITABLE
    if unknown:
        raise HTTPException(400, f"Not editable: {', '.join(sorted(unknown))}")

    for key, value in updates.items():
        if not isinstance(value, (int, float)):
            raise HTTPException(400, f"{key} must be a number")
        if value <= 0:
            raise HTTPException(400, f"{key} must be greater than zero")
        stored[key] = value

    stored["calibrated"] = False  # hand-edited, no longer purely measured
    save_thresholds(stored)
    return get_thresholds()


@router.get("/calibration")
def calibration():
    cfg = load_thresholds()
    data = cfg.get("calibration")
    if not data:
        raise HTTPException(
            404, "No calibration on record. Run: python -m tools.calibrate "
                 "--corpus ./data/corpus")
    return {
        "calibration": data,
        "chart_url": to_url(CALIBRATION_CHART) if CALIBRATION_CHART.exists() else None,
        "luma_threshold": cfg.get("luma_threshold"),
        "chroma_threshold": cfg.get("chroma_threshold"),
    }


@router.get("/stats")
def stats(db=Depends(get_db)):
    latest = db.scalar(select(Run).order_by(Run.id.desc()).limit(1))
    total_products = db.scalar(select(func.count()).select_from(Product)) or 0
    total_versions = db.scalar(select(func.count()).select_from(ArtworkVersion)) or 0

    verdicts: dict[str, int] = {}
    severities: dict[str, int] = {}
    awaiting = 0
    if latest:
        verdicts = dict(db.execute(
            select(Finding.verdict, func.count())
            .where(Finding.run_id == latest.id).group_by(Finding.verdict)).all())
        severities = dict(db.execute(
            select(Finding.severity, func.count())
            .where(Finding.run_id == latest.id).group_by(Finding.severity)).all())

        findings = db.scalars(
            select(Finding).where(Finding.run_id == latest.id,
                                  Finding.verdict != "PASS")).all()
        acks = ack_map(db, [f.product_id for f in findings],
                       [f.current_version_id for f in findings])
        for f in findings:
            _r, acknowledged = decorate_regions(f, acks)
            if not acknowledged:
                awaiting += 1

    # Trend across the last six completed runs, oldest first.
    recent = db.scalars(
        select(Run).where(Run.status == "COMPLETE")
        .order_by(Run.id.desc()).limit(6)).all()
    trend = []
    for r in reversed(recent):
        counts = dict(db.execute(
            select(Finding.verdict, func.count())
            .where(Finding.run_id == r.id).group_by(Finding.verdict)).all())
        material = db.scalar(
            select(func.count()).select_from(Finding)
            .where(Finding.run_id == r.id, Finding.severity == "MATERIAL")) or 0
        trend.append({
            "run_id": r.id,
            "started_at": r.started_at,
            "stale": counts.get("STALE_VERSION", 0),
            "pass": counts.get("PASS", 0),
            "unknown": counts.get("UNKNOWN_IMAGE", 0),
            "error": counts.get("ERROR", 0),
            "material": material,
        })

    return {
        "products": total_products,
        "versions": total_versions,
        "latest_run": {
            "id": latest.id, "status": latest.status,
            "started_at": latest.started_at, "finished_at": latest.finished_at,
            "images_total": latest.images_total,
            "images_processed": latest.images_processed,
            "images_cached": latest.images_cached,
        } if latest else None,
        "verdicts": verdicts,
        "severities": severities,
        "awaiting_review": awaiting,
        "trend": trend,
    }
