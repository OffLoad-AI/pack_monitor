"""Command-line entry point for a run.

    python -m pipeline.run --input ./data/corpus/scraped/run_2026_01

The work itself lives in `runner`: identification in `core.engine`, what a match
means in `domains.packaging`, and batch execution in `runner.orchestrator`. This
module is the CLI and the names older callers import.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from core.paths import DIFF_DIR, PIPELINE_VERSION  # noqa: F401  (re-exported)
from db.models import Finding
from db.session import SessionLocal
from domains.packaging.overlay import prune_diff_dirs as _prune_diff_dirs
from runner.executor import process_image  # noqa: F401  (re-exported)
from runner.orchestrator import (  # noqa: F401  (re-exported)
    IMAGE_EXTENSIONS,
    discover_images,
    reap_stale_runs,
    run_pipeline,
)

__all__ = [
    "DIFF_DIR", "IMAGE_EXTENSIONS", "PIPELINE_VERSION", "discover_images",
    "main", "process_image", "prune_diff_dirs", "reap_stale_runs", "run_pipeline",
]


def prune_diff_dirs(keep: int = 6) -> int:
    return _prune_diff_dirs(DIFF_DIR, keep)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pipeline.run")
    ap.add_argument("--input", required=True)
    ap.add_argument("--workers", type=int, default=None,
                    help="worker processes (default: cores, capped by free memory)")
    ap.add_argument("--no-cache", action="store_true",
                    help="re-evaluate every image instead of carrying forward "
                         "unchanged verdicts from the previous run")
    args = ap.parse_args(argv)

    run_id = run_pipeline(Path(args.input), workers=args.workers,
                          use_cache=not args.no_cache)

    with SessionLocal() as db:
        rows = db.execute(
            select(Finding.verdict).where(Finding.run_id == run_id)).all()
    counts: dict[str, int] = {}
    for (verdict,) in rows:
        counts[verdict] = counts.get(verdict, 0) + 1
    print(json.dumps({"run_id": run_id, "verdicts": counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
