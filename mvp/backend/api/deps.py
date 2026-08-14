"""Session handling and row-to-schema conversion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from sqlalchemy.orm import Session

from core.paths import DATA_DIR
from core.types import SEVERITY_RANK
from db.models import Comparison
from db.session import SessionLocal

from .schemas import ComparisonDetailOut, ComparisonOut, RegionOut, StageOut


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _served_path(path: str | None) -> str | None:
    """Turn an absolute source path into one the static mount can serve.

    Uploads live under `data/`, so they serve directly. A path outside `data/` —
    a corpus image opened from the harness, say — cannot be served, and returning
    it anyway would render as a broken image with no explanation. Returning
    `None` lets the UI say "not available" instead.
    """
    if not path:
        return None
    p = Path(path)
    try:
        if p.is_absolute():
            return str(p.resolve().relative_to(DATA_DIR.resolve())).replace("\\", "/")
        return str(p).replace("\\", "/")
    except ValueError:
        return None


def comparison_out(row: Comparison, *, region_count: int | None = None,
                   worst: str | None = None) -> ComparisonOut:
    regions = row.regions if region_count is None else None
    count = region_count if region_count is not None else len(regions or [])
    if worst is None:
        severities = [r.severity for r in (regions or [])]
        worst = max(severities, key=lambda s: SEVERITY_RANK.get(s, 0)) if severities else "NONE"

    return ComparisonOut(
        id=row.id, label=row.label,
        reference_path=row.reference_path,
        marketplace_path=row.marketplace_path,
        reference_sha256=row.reference_sha256,
        marketplace_sha256=row.marketplace_sha256,
        verdict=row.verdict, confidence=row.confidence or 0.0,
        status=row.status, error=row.error,
        duration_ms=row.duration_ms or 0.0,
        pipeline_version=row.pipeline_version,
        created_at=row.created_at,
        region_count=count, worst_severity=worst,
        reference_image=_served_path(row.reference_path),
        marketplace_image=_served_path(row.marketplace_path),
    )


def comparison_detail(row: Comparison) -> ComparisonDetailOut:
    base = comparison_out(row)
    return ComparisonDetailOut(
        **base.model_dump(),
        config=json.loads(row.config_json or "{}"),
        stages=[StageOut(
            stage=s.stage, ordinal=s.ordinal, status=s.status,
            confidence=s.confidence, duration_ms=s.duration_ms,
            metrics=json.loads(s.metrics_json or "{}"),
            artifacts=json.loads(s.artifacts_json or "{}"),
            notes=json.loads(s.notes_json or "[]"),
        ) for s in row.stages],
        regions=[RegionOut(
            id=r.id, ordinal=r.ordinal, x=r.x, y=r.y, w=r.w, h=r.h,
            area_fraction=r.area_fraction,
            reference_text=r.reference_text, marketplace_text=r.marketplace_text,
            ocr_reliable=r.ocr_reliable, difference_type=r.difference_type,
            severity=r.severity, detail=r.detail,
            ref_crop_path=r.ref_crop_path, mkt_crop_path=r.mkt_crop_path,
            signal=r.signal,
        ) for r in row.regions],
    )
