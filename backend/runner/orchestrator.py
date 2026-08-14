"""Running a batch, start to finish.

Discover the work, decide what can be skipped, feed the pool, persist what comes
back. Everything about *how an image is identified* lives elsewhere.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from sqlalchemy import select

from core.config import load_config
from core.logging import get_logger
from core.paths import DIFF_DIR, PIPELINE_VERSION
from db.models import Run, utcnow
from db.session import SessionLocal, init_db
from domains.packaging.overlay import prune_diff_dirs
from domains.packaging.registry import build_candidate_sets, current_candidate

from . import cache as C
from . import executor as X
from . import persistence as P

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# How many completed runs keep their overlays. They are regenerable, and unbounded
# this directory grew to 2.5GB and filled the disk.
KEEP_DIFF_RUNS = 6

log = get_logger("runner")


def discover_images(input_dir: Path) -> list[tuple[Path, str]]:
    """List `(path, product_id)` for a run input directory.

    Product association comes from the scraper's manifest. The pipeline must never
    read the *version* out of a filename — that encoding exists only so the test
    harness can check answers, and reading it would let the pipeline cheat.
    """
    manifest_path = input_dir / "scrape_manifest.json"
    mapping: dict[str, str] = {}
    if manifest_path.exists():
        raw = json.loads(manifest_path.read_text())
        mapping = {k: v["product_id"] for k, v in raw.items()}

    out = []
    for p in sorted(input_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        product_id = mapping.get(p.name)
        if product_id is None:
            # Fallback for hand-assembled input directories: the SKU prefix. This
            # reads the product, never the version.
            product_id = p.name.split("__")[0]
        out.append((p, product_id))
    return out


def reap_stale_runs() -> int:
    """Fail runs left RUNNING by a killed process.

    Only one run executes at a time, so a run still marked RUNNING when another
    starts is orphaned by definition. Without this, a killed run blocks every
    subsequent one forever behind the "already in progress" check.
    """
    init_db()
    with SessionLocal() as db:
        stale = db.scalars(select(Run).where(Run.status == "RUNNING")).all()
        for run in stale:
            run.status = "FAILED"
            run.error = "Run did not finish (process exited)."
            run.finished_at = utcnow()
        db.commit()
        return len(stale)


def run_pipeline(input_dir: Path, workers: int | None = None,
                 progress=None, cfg=None, on_start=None,
                 use_cache: bool = True) -> int:
    """Process a directory of listing images and record the findings."""
    input_dir = Path(input_dir).resolve()
    engine_cfg = _resolve_config(cfg)
    cfg_flat = engine_cfg.to_flat()

    init_db()
    reap_stale_runs()

    with SessionLocal() as db:
        csets = build_candidate_sets(db)
        if not csets:
            raise RuntimeError(
                "No artwork versions registered. Run `python -m pipeline.references "
                "--corpus ./data/corpus` first.")

        images = discover_images(input_dir)
        known = [(p, pid) for p, pid in images if pid in csets]
        skipped = len(images) - len(known)

        run = Run(
            pipeline_version=PIPELINE_VERSION,
            input_dir=str(input_dir),
            images_total=len(known),
            # Frozen here so a later recalibration cannot rewrite this run's
            # verdicts. This is what makes a completed run reproducible.
            config_json=json.dumps(cfg_flat, sort_keys=True),
            status="RUNNING",
        )
        db.add(run)
        db.commit()
        run_id = run.id
        if on_start:
            # Let the caller learn the run id as soon as it exists, so an API
            # client can stream progress while the run is still working.
            on_start(run_id)

        prev_id = C.previous_run_id(db, run_id)
        previous = (C.previous_index(db, prev_id)
                    if prev_id and use_cache else {})
        current_ids = {pid: int(current_candidate(cs).id)
                       for pid, cs in csets.items()}
        tasks, cached = C.partition(known, previous, current_ids)

    log.info("run.start", run_id=run_id, input_dir=str(input_dir),
             images=len(known), to_process=len(tasks), cached=len(cached),
             skipped_unknown_product=skipped, calibrated=engine_cfg.calibrated)
    if not engine_cfg.calibrated:
        # Defaults are a placeholder for measurement, and a run made with them is
        # not comparable to a calibrated one. Silence here is how that gets missed.
        log.warning("run.uncalibrated",
                    hint="thresholds are defaults; run `python -m tools.calibrate`")

    started = time.time()
    processed = 0

    with SessionLocal() as db:
        processed += P.carry_forward_cached(db, run_id, cached)
        run_row = db.get(Run, run_id)
        run_row.images_cached = len(cached)
        run_row.images_processed = processed
        db.commit()

    if progress:
        progress(processed, len(known))

    n_workers = X.resolve_worker_count(workers, len(tasks))
    diff_dir = DIFF_DIR / str(run_id)
    if tasks:
        DIFF_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with SessionLocal() as db:
            committer = P.BatchCommitter()

            def on_result(res: dict) -> None:
                nonlocal processed
                P.persist_result(db, run_id, res)
                processed += 1
                committer.record()
                committer.maybe_commit(db, run_id, processed)
                if res["verdict"] == "ERROR":
                    log.error("image.error", run_id=run_id,
                              path=res["source_path"], error=res["error"])
                if progress:
                    progress(processed, len(known))

            X.map_tasks(cfg_flat, csets, diff_dir, tasks, n_workers, on_result)
            committer.commit(db, run_id, processed)
    except Exception as exc:  # noqa: BLE001 - record the failure, do not hide it
        log.error("run.failed", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        with SessionLocal() as db:
            P.mark_failed(db, run_id, f"{type(exc).__name__}: {exc}")
        raise

    prune_diff_dirs(DIFF_DIR, KEEP_DIFF_RUNS)

    with SessionLocal() as db:
        P.mark_complete(db, run_id, processed, len(cached))

    elapsed = time.time() - started
    log.info("run.complete", run_id=run_id, images=processed,
             cached=len(cached), seconds=round(elapsed, 1),
             images_per_second=round(processed / max(elapsed, 1e-9), 1))

    if progress is None:
        print(f"run {run_id}: {processed} images in {elapsed:.1f}s "
              f"({processed / max(elapsed, 1e-9):.1f}/s), "
              f"{len(cached)} from cache, {skipped} skipped (unknown product)")
    return run_id


def _resolve_config(cfg):
    """Accept an EngineConfig, a flat mapping, or nothing."""
    from core.config import EngineConfig

    if cfg is None:
        return load_config()
    if isinstance(cfg, EngineConfig):
        return cfg
    return EngineConfig.from_flat(dict(cfg))
