"""Writing run results to the database.

Only the parent process writes. Workers return plain dicts and the parent persists
them, which sidesteps concurrent SQLite writers entirely rather than trying to make
them work.
"""

from __future__ import annotations

import json
import time

from db.models import Finding, Run, ScrapedImage, utcnow


class BatchCommitter:
    """Commits on a count or a deadline, whichever comes first.

    The previous implementation committed once per image. Under WAL that is an
    fsync per image, and it also re-read the `Run` row each time to bump a counter.
    Batching removes almost all of that while keeping progress fresh enough for the
    progress stream, which polls twice a second — so the deadline matters as much
    as the batch size, and a batch that fills slowly must not stall the UI.
    """

    def __init__(self, batch_size: int = 25, max_interval: float = 0.5):
        self.batch_size = batch_size
        self.max_interval = max_interval
        self._pending = 0
        self._last = time.monotonic()

    def record(self) -> None:
        self._pending += 1

    def due(self) -> bool:
        return (self._pending >= self.batch_size
                or (self._pending > 0
                    and time.monotonic() - self._last >= self.max_interval))

    def commit(self, db, run_id: int, processed: int) -> None:
        run = db.get(Run, run_id)
        if run is not None:
            run.images_processed = processed
        db.commit()
        self._pending = 0
        self._last = time.monotonic()

    def maybe_commit(self, db, run_id: int, processed: int) -> bool:
        if not self.due():
            return False
        self.commit(db, run_id, processed)
        return True


def _trace_to_store(res: dict) -> str | None:
    """Keep the stage trace for findings someone will actually investigate.

    A clean pass has nothing to explain — and storing a trace for every image would
    add tens of megabytes per run, kept forever, almost all of it for images nobody
    will ever look at. Refusals, stale findings and errors are exactly the ones
    where "why did it decide that?" gets asked, so those keep theirs.
    """
    if res.get("verdict") == "PASS":
        return None
    trace = res.get("trace")
    return json.dumps(trace) if trace else None


def persist_result(db, run_id: int, res: dict) -> None:
    """Stage one image's rows. Does not commit — the caller batches."""
    img = ScrapedImage(
        run_id=run_id, product_id=res["product_id"],
        source_path=res["source_path"], sha256=res["sha256"],
        width=res["width"], height=res["height"],
    )
    db.add(img)
    db.flush()
    db.add(Finding(
        run_id=run_id, product_id=res["product_id"], scraped_image_id=img.id,
        verdict=res["verdict"], matched_version_id=res["matched_version_id"],
        current_version_id=res["current_version_id"],
        match_method=res["match_method"], confidence=res["confidence"],
        diff_map_path=res["diff_map_path"],
        regions_json=json.dumps(res["regions"]),
        severity=res["severity"], error=res["error"],
        stage_trace_json=_trace_to_store(res),
    ))


def carry_forward_cached(db, run_id: int,
                         cached: list[tuple[str, str, str, int]]) -> int:
    """Copy previous verdicts forward for files that did not need reprocessing."""
    for source_path, pid, sha, prev_img_id in cached:
        prev_finding = db.scalar(
            _select_finding_for(prev_img_id))
        prev_img = db.get(ScrapedImage, prev_img_id)
        img = ScrapedImage(
            run_id=run_id, product_id=pid, source_path=source_path, sha256=sha,
            width=prev_img.width, height=prev_img.height)
        db.add(img)
        db.flush()
        if prev_finding is not None:
            db.add(Finding(
                run_id=run_id, product_id=pid, scraped_image_id=img.id,
                verdict=prev_finding.verdict,
                matched_version_id=prev_finding.matched_version_id,
                current_version_id=prev_finding.current_version_id,
                match_method=prev_finding.match_method,
                confidence=prev_finding.confidence,
                diff_map_path=prev_finding.diff_map_path,
                regions_json=prev_finding.regions_json,
                severity=prev_finding.severity,
            ))
    return len(cached)


def _select_finding_for(scraped_image_id: int):
    from sqlalchemy import select

    return select(Finding).where(Finding.scraped_image_id == scraped_image_id)


def mark_complete(db, run_id: int, processed: int, cached: int) -> None:
    run = db.get(Run, run_id)
    run.status = "COMPLETE"
    run.images_processed = processed
    run.images_cached = cached
    run.finished_at = utcnow()
    db.commit()


def mark_failed(db, run_id: int, error: str) -> None:
    run = db.get(Run, run_id)
    if run is None:
        return
    run.status = "FAILED"
    run.error = error
    run.finished_at = utcnow()
    db.commit()
