"""Threshold configuration.

The pipeline never hardcodes a threshold — it reads config/thresholds.json, which
`tools.calibrate` writes from the measured noise floor. A run freezes this file's
contents into `Run.config_json` at start, so recalibrating later cannot rewrite the
verdicts of a completed run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.paths import (  # noqa: F401  (re-exported for existing callers)
    CONFIG_PATH,
    PIPELINE_VERSION,
    REPO_ROOT,
)

# Used only when calibration has not run yet; `tools.calibrate` overwrites these.
DEFAULTS: dict[str, Any] = {
    "luma_threshold": 32,
    "chroma_threshold": 14,
    # Forgive up to this much misregistration when differencing (see diff.diff_score).
    "tolerance_radius": 1,
    "clean_fraction": 0.012,
    "region_changed_fraction": 0.02,
    # Stage 4 ranks candidates against each other; the winner must beat the runner-up
    # by this factor to be trusted, rather than clearing any absolute bar.
    #
    # Chosen from measurement, not taste, and against the right objective. Loosening
    # this buys a little identification accuracy and pays for it in false alarms:
    # at 1.10 the corpus gains 0.2 points of accuracy and two images of approved
    # artwork get reported as stale. Reporting good artwork as stale is the failure
    # that gets a compliance tool switched off, so the gate is set to the tightest
    # value that produces none, and accuracy takes what is left (>98% at every
    # quality). Refusing near a tie is the right failure mode: where this gate
    # rejects, the ranking is barely better than a coin toss, and a foreign image —
    # a seller's own photograph — scores alike against every version and lands here
    # by design.
    "region_margin_ratio": 1.12,
    # Clip on the per-region signal, so one heavily recoloured region cannot swamp a
    # small text edit elsewhere in the same sum.
    "region_signal_cap": 3.0,
    # Average only this share of a region's most-changed pixels. A changed digit is
    # a few percent of its bounding box; a plain mean buries it in the unchanged
    # background that shares the box.
    "region_signal_top_fraction": 0.05,
    # Whole-image screening can afford an aggressive open: it only has to spot gross
    # differences, and the open buys a cleaner noise floor.
    "morph_open": 3,
    # Region checks must not open at all. A changed digit is a 2-3px stroke once the
    # listing image has been downscaled, and a 3x3 open erases it completely — which
    # would silently discard exactly the nutrition drift this tool exists to catch.
    "region_morph_open": 1,
    # The spec suggests 7px, enough to merge adjacent characters. 25px also merges a
    # logo or a badge into one box, which is the unit a reviewer actually acts on —
    # it halves the region count without ever bridging two separate edits, the
    # closest of which (a nutrient's per-100g and per-serving columns) sit 300px apart.
    "morph_close": 25,
    # A diffuse change touching most of the artwork is one finding ("the palette
    # shifted"), not fifty. Collapse to a single region past this coverage.
    "global_change_area_fraction": 0.25,
    "global_change_min_regions": 20,
    # Reference-vs-reference: our own files, pixel-aligned, no compression between
    # them, so there is no misregistration to forgive and no reason to blur the test.
    "reference_luma_threshold": 10,
    "reference_chroma_threshold": 10,
    "reference_tolerance_radius": 0,
    # Deviation from the spec's 0.05%, and a necessary one: 0.05% of a 1500x1500
    # artwork is 1125px, but a single changed digit in a nutrition panel measures
    # about 330px. The spec's figure discards exactly the drift this tool exists to
    # detect. Reference-vs-reference diffs are noise-free (two of our own PNGs, no
    # compression between them), so the filter only needs to drop antialiasing
    # speckle and can safely sit an order of magnitude lower.
    "min_region_area_fraction": 0.00005,
    "border_uniform_tolerance": 10,
    "max_border_crop_fraction": 0.30,
    "calibrated": False,
}


def load_thresholds(path: Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else CONFIG_PATH
    cfg = dict(DEFAULTS)
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text()))
        except json.JSONDecodeError:
            pass
    return cfg


def save_thresholds(cfg: dict[str, Any], path: Path | None = None) -> Path:
    """Write only what was actually calibrated.

    Snapshotting every default into the file would make a stale file silently
    shadow later changes to the pipeline's own defaults. The complete resolved
    configuration is still frozen per run, in `Run.config_json`, which is what
    reproducibility actually depends on.
    """
    p = Path(path) if path else CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, sort_keys=True))
    return p
