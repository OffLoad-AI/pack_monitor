"""Comparison routes.

Small and pair-shaped. There is no run orchestration here because there are no
runs: the unit of work is one pair, and the batch endpoint is a convenience that
creates several of them rather than a different kind of object.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from core.paths import UPLOAD_DIR
from core.types import SEVERITY_RANK, VERDICTS
from db.models import Comparison, ComparisonRegion, ComparisonStage
from domains.packaging.compare import stage_names

from .. import worker
from ..deps import comparison_detail, comparison_out, get_db
from ..schemas import BatchCreatedOut, ComparisonDetailOut, CreatedOut, Page, StageOut

router = APIRouter(prefix="/api/comparisons", tags=["comparisons"])

# `ref__<name>.png` / `mkt__<name>.png` — the batch pairing convention.
_PAIR_RE = re.compile(r"^(ref|mkt)__(.+?)\.[A-Za-z0-9]+$")
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
MAX_UPLOAD_BYTES = 40 * 1024 * 1024


def _save_upload(upload: UploadFile, prefix: str) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            400, f"{upload.filename!r} is not an image this tool reads. "
                 f"Use PNG, JPEG, WebP, BMP or TIFF.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}_{prefix}{suffix}"
    size = 0
    with dest.open("wb") as fh:
        while chunk := upload.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    400, f"{upload.filename!r} is larger than "
                         f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB.")
            fh.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"{upload.filename!r} is empty.")
    return dest


@router.post("", status_code=202, response_model=CreatedOut)
def create(reference: UploadFile = File(...),
           marketplace: UploadFile = File(...),
           label: str | None = Form(None)) -> CreatedOut:
    """Accept a pair and start comparing it.

    Returns immediately with an id. The work happens on a worker thread and
    progress is reported through the database, so the client can either poll or
    stream `/{id}/stream`.
    """
    ref_path = _save_upload(reference, "reference")
    mkt_path = _save_upload(marketplace, "marketplace")
    comparison_id = worker.create_comparison(ref_path, mkt_path, label)
    worker.start(comparison_id)
    return CreatedOut(id=comparison_id, status=worker.QUEUED)


@router.post("/batch", status_code=202, response_model=BatchCreatedOut)
def create_batch(files: list[UploadFile] = File(...)) -> BatchCreatedOut:
    """Pair files by the `ref__<name>` / `mkt__<name>` naming convention.

    Files that do not pair up are reported back rather than silently dropped —
    a batch that quietly ran 6 of your 8 pairs is worse than one that says so.
    """
    refs: dict[str, Path] = {}
    mkts: dict[str, Path] = {}
    unmatched: list[str] = []

    for upload in files:
        m = _PAIR_RE.match(Path(upload.filename or "").name)
        if not m:
            unmatched.append(upload.filename or "(unnamed)")
            continue
        side, key = m.group(1), m.group(2)
        saved = _save_upload(upload, side)
        (refs if side == "ref" else mkts)[key] = saved

    created: list[CreatedOut] = []
    for key in sorted(set(refs) & set(mkts)):
        comparison_id = worker.create_comparison(refs[key], mkts[key], label=key)
        worker.start(comparison_id)
        created.append(CreatedOut(id=comparison_id, status=worker.QUEUED))

    for key in sorted(set(refs) ^ set(mkts)):
        unmatched.append(f"{key} (no {'marketplace' if key in refs else 'reference'} image)")

    if not created:
        raise HTTPException(
            400, "No pairs were found. Name files ref__<name>.png and "
                 "mkt__<name>.png so they can be matched up.")
    return BatchCreatedOut(created=created, unmatched=unmatched)


@router.get("", response_model=Page)
def list_comparisons(db: Session = Depends(get_db),
                     verdict: list[str] | None = Query(None),
                     offset: int = 0, limit: int = 50) -> Page:
    stmt = select(Comparison)
    if verdict:
        unknown = [v for v in verdict if v not in VERDICTS]
        if unknown:
            raise HTTPException(400, f"Unknown verdict(s): {', '.join(unknown)}")
        stmt = stmt.where(Comparison.verdict.in_(verdict))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Comparison.id.desc()).offset(offset).limit(limit)).all()

    # Region counts in one query rather than one per row: the history table shows
    # fifty at a time and lazy-loading each row's regions is fifty round trips.
    ids = [r.id for r in rows]
    counts: dict[int, int] = {}
    worst: dict[int, str] = {}
    if ids:
        for cid, severity, n in db.execute(
                select(ComparisonRegion.comparison_id, ComparisonRegion.severity,
                       func.count())
                .where(ComparisonRegion.comparison_id.in_(ids))
                .group_by(ComparisonRegion.comparison_id, ComparisonRegion.severity)):
            counts[cid] = counts.get(cid, 0) + n
            if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(worst.get(cid, "NONE"), 0):
                worst[cid] = severity

    return Page(total=total, offset=offset, limit=limit,
                items=[comparison_out(r, region_count=counts.get(r.id, 0),
                                      worst=worst.get(r.id, "NONE")) for r in rows])


@router.get("/stages", response_model=list[str])
def pipeline_stages() -> list[str]:
    """The stage list, so the UI can draw the pipeline before it has run."""
    return stage_names()


@router.get("/{comparison_id}", response_model=ComparisonDetailOut)
def get_comparison(comparison_id: int,
                   db: Session = Depends(get_db)) -> ComparisonDetailOut:
    row = db.get(Comparison, comparison_id)
    if row is None:
        raise HTTPException(404, f"No comparison with id {comparison_id}.")
    return comparison_detail(row)


@router.get("/{comparison_id}/stages", response_model=list[StageOut])
def get_stages(comparison_id: int, db: Session = Depends(get_db)) -> list[StageOut]:
    row = db.get(Comparison, comparison_id)
    if row is None:
        raise HTTPException(404, f"No comparison with id {comparison_id}.")
    return comparison_detail(row).stages


@router.delete("/{comparison_id}", status_code=204)
def delete_comparison(comparison_id: int, db: Session = Depends(get_db)) -> None:
    row = db.get(Comparison, comparison_id)
    if row is None:
        raise HTTPException(404, f"No comparison with id {comparison_id}.")
    # Artefacts are the bulk of what a comparison costs on disk, and orphaning
    # them fills the disk silently. The other build learned this the hard way.
    from core.paths import comparison_dir

    shutil.rmtree(comparison_dir(comparison_id), ignore_errors=True)
    db.delete(row)
    db.commit()


@router.get("/{comparison_id}/stream")
async def stream(comparison_id: int):
    """Stage-by-stage progress as it runs.

    Polls the database twice a second and emits only on change, which keeps a
    finished comparison from sending the same payload forever while a browser
    tab sits open on it.
    """
    expected = stage_names()

    async def events():
        last: str | None = None
        # A comparison that never starts must not hold a connection open for
        # ever; 10 minutes is far longer than any single pair takes.
        for _ in range(1200):
            db = None
            try:
                from db.session import SessionLocal

                db = SessionLocal()
                row = db.get(Comparison, comparison_id)
                if row is None:
                    yield {"event": "error",
                           "data": json.dumps({"detail": "No such comparison."})}
                    return

                done = db.scalars(
                    select(ComparisonStage)
                    .where(ComparisonStage.comparison_id == comparison_id)
                    .order_by(ComparisonStage.ordinal)).all()

                payload = {
                    "id": row.id,
                    "status": row.status,
                    "verdict": row.verdict,
                    "confidence": row.confidence,
                    "expected_stages": expected,
                    "completed": [
                        {"stage": s.stage, "status": s.status,
                         "duration_ms": s.duration_ms, "confidence": s.confidence,
                         "notes": json.loads(s.notes_json or "[]")}
                        for s in done],
                }
                blob = json.dumps(payload, sort_keys=True)
                if blob != last:
                    last = blob
                    yield {"event": "progress", "data": blob}

                if row.status in (worker.COMPLETE, worker.FAILED_STATUS):
                    yield {"event": "done", "data": blob}
                    return
            finally:
                if db is not None:
                    db.close()
            await asyncio.sleep(0.5)

    return EventSourceResponse(events())
