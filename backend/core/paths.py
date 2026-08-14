"""Filesystem layout and the processing version, in one place.

These were previously re-derived in five modules from three different anchor
points, so moving a directory meant finding all of them.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = REPO_ROOT / "data"
DIFF_DIR = DATA_DIR / "diffs"
THUMB_DIR = DATA_DIR / "thumbs"
DEFAULT_DB_PATH = DATA_DIR / "db.sqlite"

CONFIG_PATH = REPO_ROOT / "config" / "thresholds.json"
CALIBRATION_DIR = REPO_ROOT / "calibration"

# Stamped onto every run. Bump when a change would alter verdicts, so stored runs
# stay attributable to the code that produced them.
PIPELINE_VERSION = "1.0.0"
