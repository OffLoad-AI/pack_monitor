"""One pair, end to end.

The adapter between the general pair-comparison engine and this problem. It is
thin on purpose: everything domain-specific about packaging lives in the words the
stages use, not in the control flow, so pointing this at a different kind of image
pair means changing the copy and nothing else.

Deliberately usable without a database. The accuracy harness runs several hundred
pairs and has no use for persistence, and a comparison that can only run inside a
web request is a comparison that cannot be measured.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from core.config import EngineConfig, load_config
from core.engine import Engine
from core.ocr import get_engine
from core.paths import COMPARISON_DIR, DATA_DIR
from core.trace import StageTrace, TraceRecorder
from core.types import ComparisonResult, PairContext

StageListener = Callable[[StageTrace], None]


def compare_pair(reference_path: str | Path,
                 marketplace_path: str | Path,
                 *,
                 comparison_id: int,
                 config: EngineConfig | None = None,
                 artifacts_root: Path | None = None,
                 data_root: Path | None = None,
                 ocr_engine=None,
                 on_stage: StageListener | None = None) -> ComparisonResult:
    """Compare one reference image against one marketplace image.

    `comparison_id` decides where artefacts are written, so it is required even
    when nothing is being persisted — the harness passes an index.
    """
    cfg = config or load_config()
    root = Path(artifacts_root) if artifacts_root else COMPARISON_DIR / str(comparison_id)
    droot = Path(data_root) if data_root else DATA_DIR
    root.mkdir(parents=True, exist_ok=True)

    recorder = TraceRecorder(comparison_id, root, droot, on_trace=on_stage)
    ctx = PairContext(
        comparison_id=comparison_id,
        reference_path=Path(reference_path),
        marketplace_path=Path(marketplace_path),
        config=cfg,
        recorder=recorder,
        ocr=(ocr_engine if ocr_engine is not None
             else get_engine(cfg.ocr.backend, cfg.ocr.det_limit_side_len)),
    )

    return Engine(config=cfg).compare(ctx)


def stage_names() -> list[str]:
    """The pipeline's stages in order — used by the UI to render a skeleton
    before any of them have run."""
    from core.engine import default_stages

    return [s.name for s in default_stages()]
