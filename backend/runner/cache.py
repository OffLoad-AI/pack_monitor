"""Deciding what does not need reprocessing.

The cache key is **source path + file hash + the candidate set's current approved
version**. That third component is the interesting one: unchanged bytes are only
safe to skip while the *question* is also unchanged. Once new artwork is approved,
"is this listing stale?" has a different answer for the very same bytes, so
approving artwork re-opens every listing for that product automatically.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from core.imaging.loader import sha256_file
from db.models import Finding, Run, ScrapedImage

# (source_path, product_id, sha)
Task = tuple[str, str, str]
# (source_path, product_id, sha, previous_scraped_image_id)
CachedTask = tuple[str, str, str, int]


def previous_run_id(db, before_run_id: int) -> int | None:
    return db.scalar(
        select(Run.id)
        .where(Run.id < before_run_id, Run.status == "COMPLETE")
        .order_by(Run.id.desc()).limit(1))


def previous_index(db, run_id: int) -> dict[str, tuple[int, str, int | None]]:
    """`source_path -> (scraped_image_id, sha256, current_version_id)`."""
    rows = db.execute(
        select(ScrapedImage.source_path, ScrapedImage.sha256, ScrapedImage.id,
               Finding.current_version_id)
        .join(Finding, Finding.scraped_image_id == ScrapedImage.id, isouter=True)
        .where(ScrapedImage.run_id == run_id)).all()
    return {sp: (sid, sha, cvid) for sp, sha, sid, cvid in rows}


def partition(known: list[tuple[Path, str]],
              previous: dict[str, tuple[int, str, int | None]],
              current_version_id: dict[str, int]
              ) -> tuple[list[Task], list[CachedTask]]:
    """Split discovered work into "must process" and "carry forward".

    Sorted by product first: workers pull tasks in submission order, so this keeps
    each worker on one product's references at a time and lets the small per-worker
    image cache actually hit.
    """
    tasks: list[Task] = []
    cached: list[CachedTask] = []

    ordered = sorted(known, key=lambda t: (t[1], str(t[0])))
    for path, pid in ordered:
        sha = sha256_file(path)
        hit = previous.get(str(path))
        if hit and hit[1] == sha and hit[2] == current_version_id.get(pid):
            cached.append((str(path), pid, sha, hit[0]))
        else:
            tasks.append((str(path), pid, sha))
    return tasks, cached
