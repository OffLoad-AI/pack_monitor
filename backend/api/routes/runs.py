"""Run lifecycle, live progress, and the findings queue."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from db.models import ArtworkVersion, Finding, Product, Run, ScrapedImage, utcnow
from db.session import SessionLocal
from pipeline.config import REPO_ROOT
from pipeline.references import THUMB_DIR
from pipeline.run import run_pipeline

from ..deps import ack_map, decorate_regions, get_db, to_url
from ..schemas import FindingOut, Page, RunCreate, RunOut

router = APIRouter(prefix="/api", tags=["runs"])

_ACTIVE: dict[int, threading.Thread] = {}


def _run_out(db, run: Run) -> RunOut:
    counts = dict(db.execute(
        select(Finding.verdict, func.count())
        .where(Finding.run_id == run.id).group_by(Finding.verdict)).all())
    sev = dict(db.execute(
        select(Finding.severity, func.count())
        .where(Finding.run_id == run.id).group_by(Finding.severity)).all())
    return RunOut(
        id=run.id, started_at=run.started_at, finished_at=run.finished_at,
        status=run.status, pipeline_version=run.pipeline_version,
        input_dir=run.input_dir, images_total=run.images_total,
        images_processed=run.images_processed, images_cached=run.images_cached,
        error=run.error, counts=counts, severity_counts=sev,
    )


@router.get("/runs", response_model=list[RunOut])
def list_runs(db=Depends(get_db), limit: int = 50):
    runs = db.scalars(select(Run).order_by(Run.id.desc()).limit(limit)).all()
    return [_run_out(db, r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, db=Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, f"No run {run_id}")
    return _run_out(db, run)


@router.post("/runs", response_model=RunOut, status_code=202)
def start_run(body: RunCreate, db=Depends(get_db)):
    input_dir = Path(body.input_dir).expanduser()
    if not input_dir.is_absolute():
        input_dir = (REPO_ROOT / input_dir).resolve()
    if not input_dir.is_dir():
        raise HTTPException(400, f"Input directory not found: {input_dir}")

    running = db.scalar(select(Run).where(Run.status == "RUNNING").limit(1))
    if running is not None:
        raise HTTPException(409, f"Run {running.id} is still in progress")

    if db.scalar(select(func.count()).select_from(ArtworkVersion)) == 0:
        raise HTTPException(
            400, "No approved artwork is registered. Process references first: "
                 "python -m pipeline.references --corpus ./data/corpus")

    # The pipeline is blocking and owns a process pool, so it runs on a worker
    # thread and reports progress through the database rather than in-memory state.
    box: dict = {}
    ready = threading.Event()

    def _target():
        try:
            run_pipeline(input_dir, progress=lambda *_: None,
                         on_start=lambda rid: (box.__setitem__("run_id", rid), ready.set()))
        except Exception as exc:  # noqa: BLE001
            box["error"] = str(exc)
            rid = box.get("run_id")
            if rid:
                with SessionLocal() as s:
                    r = s.get(Run, rid)
                    if r and r.status == "RUNNING":
                        r.status = "FAILED"
                        r.error = str(exc)
                        r.finished_at = utcnow()
                        s.commit()
        finally:
            ready.set()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    ready.wait(timeout=30)

    run_id = box.get("run_id")
    if run_id is None:
        raise HTTPException(500, box.get("error", "Run failed to start"))
    _ACTIVE[run_id] = t

    db.expire_all()
    run = db.get(Run, run_id)
    return _run_out(db, run)


@router.get("/runs/{run_id}/progress")
async def run_progress(run_id: int):
    """Server-sent progress so the queue can be worked before the run finishes."""

    async def stream():
        last = None
        while True:
            with SessionLocal() as db:
                run = db.get(Run, run_id)
                if run is None:
                    yield {"event": "error", "data": json.dumps({"detail": "no such run"})}
                    return
                payload = _run_out(db, run).model_dump()
            if payload != last:
                yield {"event": "progress", "data": json.dumps(payload)}
                last = payload
            if payload["status"] != "RUNNING":
                yield {"event": "done", "data": json.dumps(payload)}
                return
            await asyncio.sleep(0.5)

    return EventSourceResponse(stream())


@router.get("/runs/{run_id}/findings", response_model=Page)
def run_findings(
    run_id: int,
    db=Depends(get_db),
    verdict: list[str] | None = Query(None),
    severity: list[str] | None = Query(None),
    acknowledged: bool | None = None,
    product_id: str | None = None,
    match_method: str | None = None,
    sort: str = "severity",
    order: str = "desc",
    offset: int = 0,
    limit: int = 50,
):
    stmt = select(Finding).where(Finding.run_id == run_id)
    if verdict:
        stmt = stmt.where(Finding.verdict.in_(verdict))
    if severity:
        stmt = stmt.where(Finding.severity.in_(severity))
    if product_id:
        stmt = stmt.where(Finding.product_id == product_id)
    if match_method:
        stmt = stmt.where(Finding.match_method == match_method)

    findings = db.scalars(stmt.order_by(Finding.id)).all()

    acks = ack_map(db, [f.product_id for f in findings],
                   [f.current_version_id for f in findings])
    labels = {v.id: v.version_label
              for v in db.scalars(select(ArtworkVersion)).all()}
    names = {p.id: p.name for p in db.scalars(select(Product)).all()}
    images = {i.id: i for i in db.scalars(
        select(ScrapedImage).where(ScrapedImage.run_id == run_id)).all()}

    rows = []
    for f in findings:
        regions, is_ack = decorate_regions(f, acks)
        # Acknowledgement is resolved here, so it has to be filtered here too.
        if acknowledged is not None and is_ack != acknowledged:
            continue
        img = images.get(f.scraped_image_id)
        rows.append(FindingOut(
            id=f.id, run_id=f.run_id, product_id=f.product_id,
            product_name=names.get(f.product_id),
            verdict=f.verdict, severity=f.severity, match_method=f.match_method,
            confidence=f.confidence,
            matched_version=labels.get(f.matched_version_id),
            current_version=labels.get(f.current_version_id),
            matched_version_id=f.matched_version_id,
            current_version_id=f.current_version_id,
            region_count=len(regions), acknowledged=is_ack,
            created_at=f.created_at,
            thumb_url=to_url(img.source_path) if img else None,
            source_name=Path(img.source_path).name if img else None,
        ))

    severity_rank = {"MATERIAL": 3, "UNCERTAIN": 2, "COSMETIC": 1, "NONE": 0}
    verdict_rank = {"STALE_VERSION": 3, "ERROR": 2, "UNKNOWN_IMAGE": 1, "PASS": 0}
    keys = {
        "severity": lambda r: (severity_rank.get(r.severity, 0), verdict_rank.get(r.verdict, 0)),
        "verdict": lambda r: (verdict_rank.get(r.verdict, 0),),
        "product": lambda r: (r.product_id,),
        "confidence": lambda r: (r.confidence,),
        "regions": lambda r: (r.region_count,),
        "id": lambda r: (r.id,),
    }
    # Two passes so ties break sensibly: the secondary order is always ascending by
    # product then id, whichever direction the primary sort runs. Folding the id into
    # a single descending key instead would put the highest-numbered product first
    # and fill the whole first page with one SKU.
    rows.sort(key=lambda r: (r.product_id, r.id))
    rows.sort(key=keys.get(sort, keys["severity"]), reverse=(order == "desc"))

    total = len(rows)
    return Page(items=[r.model_dump() for r in rows[offset:offset + limit]],
                total=total, offset=offset, limit=limit)
