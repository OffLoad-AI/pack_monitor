"""Getting work to processes.

Isolated here so the execution strategy can change without touching identification,
persistence or the domain. Today that is a local process pool; the interface it
exposes — submit tasks, receive result dicts as they finish — is the same shape a
queue-backed worker would present.
"""

from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import cv2

from core.config import EngineConfig
from core.context import LruImageStore
from core.engine import Engine
from domains.packaging.identify import identify_listing

# Per-worker state. A module global is the only thing a process pool initializer
# can populate, but nothing outside this module reads it.
_W: dict = {}

# Rough working-set budget per worker, used to cap concurrency on small machines.
WORKER_MEMORY_BUDGET_MB = 150


def _init_worker(cfg_flat: dict, candidate_sets: dict, diff_dir: str) -> None:
    """Build the engine once per worker process."""
    _W["engine"] = Engine(config=EngineConfig.from_flat(cfg_flat))
    _W["csets"] = candidate_sets
    _W["diff_dir"] = Path(diff_dir)
    _W["store"] = LruImageStore()
    _W["store_key"] = None
    # The pool already provides the parallelism; nested threading only contends.
    cv2.setNumThreads(1)


def _store_for(product_id: str) -> LruImageStore:
    """Reset the bounded image cache when the worker moves to a new product.

    Tasks arrive grouped by product, so a change means the previous product's
    references will not be asked for again.
    """
    if _W["store_key"] != product_id:
        _W["store"] = LruImageStore()
        _W["store_key"] = product_id
    return _W["store"]


def process_image(task: tuple[str, str, str]) -> dict:
    """Identify one listing image. Runs in a worker process."""
    source_path, product_id, sha = task
    return identify_listing(
        engine=_W["engine"],
        source_path=source_path,
        sha=sha,
        cset=_W["csets"][product_id],
        store=_store_for(product_id),
        diff_dir=_W["diff_dir"],
    )


def default_workers() -> int:
    """One per core, capped by memory.

    Each worker holds decoded references and a few difference maps. Running one per
    core regardless of RAM is how the 40-product corpus ran a machine out of memory.
    """
    cpu = os.cpu_count() or 4
    try:
        available = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        by_memory = int((available * 0.70) / (WORKER_MEMORY_BUDGET_MB * 1024 * 1024))
        return max(1, min(cpu, by_memory))
    except (ValueError, OSError, AttributeError):
        return cpu


def map_tasks(cfg_flat: dict, candidate_sets: dict, diff_dir: Path,
              tasks: list[tuple[str, str, str]], workers: int,
              on_result: Callable[[dict], None]) -> None:
    """Run every task across a process pool, calling `on_result` as each lands.

    Uses the **spawn** start method, not the platform default fork. By the time a
    run starts, this process has usually decoded images with OpenCV, which leaves
    its own thread pool running, and the API starts runs from a worker thread of a
    threaded server. Forking a multithreaded process hands the child copies of locks
    held by threads that do not exist in it, and the pool deadlocks on the first
    image — idle workers, idle parent, no error and no timeout. Spawn pays about a
    second of start-up for a clean interpreter instead.
    """
    if not tasks:
        return

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_worker,
        initargs=(cfg_flat, candidate_sets, str(diff_dir)),
        mp_context=multiprocessing.get_context("spawn"),
    ) as pool:
        futures = [pool.submit(process_image, t) for t in tasks]
        for fut in as_completed(futures):
            on_result(fut.result())


def resolve_worker_count(requested: int | None, task_count: int) -> int:
    n = requested or default_workers()
    return max(1, min(n, max(1, task_count)))
