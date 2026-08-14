"""Running a comparison, and reporting progress while it runs.

The pattern is the one already working in the other build's `POST /api/runs`: the
work happens on a worker thread and **progress is reported through the database**
rather than through in-memory state. That is what lets the SSE endpoint be a plain
poll of two tables, survive a page reload, and show the same thing to two browsers
at once.

Stages are written as they complete, not in one batch at the end. Registration
takes a couple of seconds on a 1500px pair and the screen should say what it is
doing, not sit blank and then fill in.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from core.config import EngineConfig, load_config
from core.logging import get_logger
from core.paths import COMPARISON_DIR, DATA_DIR, PIPELINE_VERSION
from core.trace import FAILED, StageTrace
from db.models import Comparison, ComparisonRegion, ComparisonStage
from db.session import SessionLocal
from domains.packaging.compare import compare_pair

log = get_logger(__name__)

QUEUED = "QUEUED"
RUNNING = "RUNNING"
COMPLETE = "COMPLETE"
FAILED_STATUS = "FAILED"

# One comparison at a time. They are CPU-bound on OpenCV and ONNX Runtime, both of
# which already use every core; running two concurrently makes both slower and
# makes the timing report meaningless.
_LOCK = threading.Lock()


def create_comparison(reference_path: Path, marketplace_path: Path,
                      label: str | None = None,
                      config: EngineConfig | None = None) -> int:
    """Insert the row and return its id, without running anything yet."""
    cfg = config or load_config()
    db = SessionLocal()
    try:
        row = Comparison(
            reference_path=str(reference_path),
            marketplace_path=str(marketplace_path),
            label=label,
            status=QUEUED,
            pipeline_version=PIPELINE_VERSION,
            config_json=json.dumps(cfg.to_flat(), sort_keys=True),
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def run_comparison(comparison_id: int) -> None:
    """Run one queued comparison to completion. Safe to call on a thread."""
    with _LOCK:
        _run(comparison_id)


def _run(comparison_id: int) -> None:
    db = SessionLocal()
    try:
        row = db.get(Comparison, comparison_id)
        if row is None:
            log.warning("comparison.missing", id=comparison_id)
            return

        cfg = EngineConfig.from_flat(json.loads(row.config_json or "{}"))
        row.status = RUNNING
        # Re-running clears the previous attempt's rows rather than appending to
        # them; a stage list with two registration rows is not a record of
        # anything.
        for stage in list(row.stages):
            db.delete(stage)
        for region in list(row.regions):
            db.delete(region)
        db.commit()

        ordinal = {"n": 0}

        def on_stage(trace: StageTrace) -> None:
            ordinal["n"] += 1
            db.add(ComparisonStage(comparison_id=comparison_id,
                                   ordinal=ordinal["n"], **trace.to_row()))
            db.commit()

        result = compare_pair(
            row.reference_path, row.marketplace_path,
            comparison_id=comparison_id, config=cfg,
            artifacts_root=COMPARISON_DIR / str(comparison_id),
            data_root=DATA_DIR,
            on_stage=on_stage)

        for i, region in enumerate(result.regions, start=1):
            x, y, w, h = region.box
            db.add(ComparisonRegion(
                comparison_id=comparison_id, ordinal=i,
                x=x, y=y, w=w, h=h, area_fraction=region.area_fraction,
                reference_text=region.reference_text,
                marketplace_text=region.marketplace_text,
                ocr_reliable=region.ocr_reliable,
                difference_type=region.difference_type,
                severity=region.severity, detail=region.detail,
                ref_crop_path=region.ref_crop_path,
                mkt_crop_path=region.mkt_crop_path,
                signal=region.signal))

        row.verdict = result.verdict
        row.confidence = result.confidence
        row.duration_ms = result.duration_ms
        row.reference_sha256 = result.reference_sha256
        row.marketplace_sha256 = result.marketplace_sha256
        row.error = result.error
        # A comparison that produced `CANNOT_COMPARE` still COMPLETEd — refusing
        # is an answer. `FAILED` is reserved for the pipeline itself breaking.
        row.status = FAILED_STATUS if result.error else COMPLETE
        db.commit()

        log.info("comparison.done", id=comparison_id, verdict=result.verdict,
                 regions=len(result.regions), ms=round(result.duration_ms))

    except Exception as exc:  # noqa: BLE001 — the row must never be left RUNNING
        log.error("comparison.failed", id=comparison_id, error=str(exc))
        db.rollback()
        row = db.get(Comparison, comparison_id)
        if row is not None:
            row.status = FAILED_STATUS
            row.error = f"{type(exc).__name__}: {exc}"
            row.verdict = row.verdict or "CANNOT_COMPARE"
            db.add(ComparisonStage(
                comparison_id=comparison_id, ordinal=999, stage="pipeline",
                status=FAILED, duration_ms=0.0,
                metrics_json=json.dumps({"error": str(exc)}),
                artifacts_json="{}",
                notes_json=json.dumps([
                    "The comparison could not be completed.",
                    f"{type(exc).__name__}: {exc}"])))
            db.commit()
    finally:
        db.close()


def start(comparison_id: int) -> threading.Thread:
    t = threading.Thread(target=run_comparison, args=(comparison_id,),
                         name=f"comparison-{comparison_id}", daemon=True)
    t.start()
    return t


def reap_stale() -> int:
    """Any comparison left RUNNING by a server restart is orphaned by definition.

    Without this the UI shows phantom progress forever on a row nothing is
    working on.
    """
    db = SessionLocal()
    try:
        stale = db.query(Comparison).filter(Comparison.status == RUNNING).all()
        for row in stale:
            row.status = FAILED_STATUS
            row.error = "Interrupted by a server restart."
            row.verdict = row.verdict or "CANNOT_COMPARE"
        db.commit()
        return len(stale)
    finally:
        db.close()
