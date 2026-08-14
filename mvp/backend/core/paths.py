"""Filesystem layout and the pipeline version, in one place.

Kept as a module rather than re-derived per caller so that moving a directory is a
one-line change. Carried over unchanged in spirit from the version-identification
build; only the directories differ, because this build stores per-comparison
artefacts rather than per-run diff overlays.
"""

from __future__ import annotations

import os
from pathlib import Path

# mvp/backend/core/paths.py -> mvp/
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("PPC_DATA_DIR", str(PROJECT_ROOT / "data")))
COMPARISON_DIR = DATA_DIR / "comparisons"
UPLOAD_DIR = DATA_DIR / "uploads"
PAIRS_DIR = DATA_DIR / "pairs"
DEFAULT_DB_PATH = DATA_DIR / "db.sqlite"

CONFIG_PATH = Path(os.environ.get("PPC_CONFIG_PATH",
                                  str(PROJECT_ROOT / "config" / "thresholds.json")))
CALIBRATION_DIR = PROJECT_ROOT / "calibration"

# Stamped onto every comparison. Bump when a change would alter verdicts, so
# stored comparisons stay attributable to the code that produced them.
PIPELINE_VERSION = "0.1.0"


def comparison_dir(comparison_id: int) -> Path:
    return COMPARISON_DIR / str(comparison_id)


def artifact_path(comparison_id: int, stage: str, name: str) -> Path:
    """`data/comparisons/{id}/{stage}/{name}` — the layout the API serves from."""
    return comparison_dir(comparison_id) / stage / name


def relative_artifact(path: Path) -> str:
    """Path relative to `data/`, which is what gets stored and served.

    Absolute paths in the database would break the moment the project moved, and
    the API mounts `data/` statically, so the relative form is also the URL.
    """
    return str(Path(path).resolve().relative_to(DATA_DIR.resolve())).replace(os.sep, "/")


def ensure_dirs() -> None:
    for d in (DATA_DIR, COMPARISON_DIR, UPLOAD_DIR, CALIBRATION_DIR):
        d.mkdir(parents=True, exist_ok=True)
