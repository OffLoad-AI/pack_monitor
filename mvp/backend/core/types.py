"""The vocabulary this pipeline speaks.

The question here is not the other build's *"which of our N known versions is this
a copy of?"* but *"are these two images the same artwork, and if not, what differs,
in words?"* — so there is no candidate set and no ranking. Every judgement is
absolute, measured against a threshold, and the types reflect that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .config import EngineConfig
from .trace import TraceRecorder

Box = tuple[int, int, int, int]

# -- verdicts ---------------------------------------------------------------
# `CANNOT_COMPARE` and `NEEDS_REVIEW` are **designed outcomes, not failures**.
# Carrying over the other build's discipline: it is better to decline than to
# guess, because reporting good artwork as changed is the failure that gets a
# compliance tool switched off.

IDENTICAL = "IDENTICAL"
MATCH = "MATCH"
MATCH_WITH_COSMETIC_DIFFERENCES = "MATCH_WITH_COSMETIC_DIFFERENCES"
DIFFERENT = "DIFFERENT"
NEEDS_REVIEW = "NEEDS_REVIEW"
CANNOT_COMPARE = "CANNOT_COMPARE"

VERDICTS = (IDENTICAL, MATCH, MATCH_WITH_COSMETIC_DIFFERENCES, DIFFERENT,
            NEEDS_REVIEW, CANNOT_COMPARE)

# -- severity ---------------------------------------------------------------

MATERIAL = "MATERIAL"
COSMETIC = "COSMETIC"
UNCERTAIN = "UNCERTAIN"
NONE = "NONE"

SEVERITIES = (MATERIAL, UNCERTAIN, COSMETIC, NONE)
# Worst first — used to reduce a region list to one verdict.
SEVERITY_RANK = {MATERIAL: 3, UNCERTAIN: 2, COSMETIC: 1, NONE: 0}

# -- difference types -------------------------------------------------------
# What changed, descriptively. Severity says how much it matters; this says what
# it was, and the UI names it for the reader.

NUMBER_CHANGED = "NUMBER_CHANGED"
NUMBER_AND_UNIT_CHANGED = "NUMBER_AND_UNIT_CHANGED"
NUMBER_FORMAT = "NUMBER_FORMAT"
TEXT_ADDED = "TEXT_ADDED"
TEXT_REMOVED = "TEXT_REMOVED"
TEXT_CHANGED = "TEXT_CHANGED"
CONFUSABLE_CHARACTERS = "CONFUSABLE_CHARACTERS"
OCR_UNRELIABLE = "OCR_UNRELIABLE"
PUNCTUATION_ONLY = "PUNCTUATION_ONLY"
# A removed certification mark is a real material change with no text to compare.
# These are not discarded; they are surfaced for human judgement.
VISUAL_ONLY = "VISUAL_ONLY"
PALETTE_SHIFT = "PALETTE_SHIFT"
NO_DIFFERENCE = "NO_DIFFERENCE"

# How a region was proposed. `PALETTE` regions are the collapsed whole-frame
# recolour; they are not read, because a recolour has no text to read and the
# text is checked by the luma-only regions extracted alongside them.
KIND_PIXEL = "PIXEL"
KIND_PALETTE = "PALETTE"


@dataclass
class OcrToken:
    text: str
    confidence: float
    box: Box


@dataclass
class OcrReading:
    """One OCR pass over one crop."""

    text: str
    tokens: list[OcrToken] = field(default_factory=list)

    @property
    def min_confidence(self) -> float:
        return min((t.confidence for t in self.tokens), default=1.0)

    @property
    def mean_confidence(self) -> float:
        if not self.tokens:
            return 1.0
        return float(np.mean([t.confidence for t in self.tokens]))


@dataclass
class RegionFinding:
    """One candidate region, from proposal through to classification.

    Carries its own evidence — both crops, both readings, the reliability flag —
    so the UI can show why a difference was called what it was called.
    """

    box: Box                                  # marketplace frame
    area_fraction: float
    kind: str = KIND_PIXEL
    reference_text: str | None = None
    marketplace_text: str | None = None
    reference_reading: OcrReading | None = None
    marketplace_reading: OcrReading | None = None
    ocr_reliable: bool = True
    # Set when one side read text, the other read nothing, and the pixels show
    # the ink is still there. That is positive evidence of a failed *read*, as
    # distinct from an unexplained difference.
    ink_intact: bool = False
    difference_type: str = NO_DIFFERENCE
    severity: str = NONE
    detail: str = ""                          # plain-language, for the UI
    ref_crop_path: str | None = None
    mkt_crop_path: str | None = None
    signal: float = 0.0                       # mean normalized diff in the box

    def as_dict(self) -> dict[str, Any]:
        x, y, w, h = self.box
        return {
            "x": x, "y": y, "w": w, "h": h,
            "kind": self.kind,
            "area_fraction": round(self.area_fraction, 8),
            "reference_text": self.reference_text,
            "marketplace_text": self.marketplace_text,
            "ocr_reliable": self.ocr_reliable,
            "difference_type": self.difference_type,
            "severity": self.severity,
            "detail": self.detail,
            "ref_crop_path": self.ref_crop_path,
            "mkt_crop_path": self.mkt_crop_path,
            "signal": round(float(self.signal), 6),
        }


@dataclass
class PairContext:
    """Working state for one pair, threaded through the stages.

    Stages read what earlier stages put here and add their own. Nothing is
    recomputed: the normalized images, the homography and the difference map are
    each produced exactly once and shared, which is what keeps a stage cheap to
    add or reorder.
    """

    comparison_id: int
    reference_path: Path
    marketplace_path: Path
    config: EngineConfig
    recorder: TraceRecorder
    ocr: Any = None                            # core.ocr.OcrEngine

    # Stage 1
    reference_sha256: str | None = None
    marketplace_sha256: str | None = None

    # Stage 0
    reference_rgb: np.ndarray | None = None    # normalized, de-padded
    marketplace_rgb: np.ndarray | None = None

    # Stage 2
    homography: np.ndarray | None = None
    warped_reference: np.ndarray | None = None
    overlap_mask: np.ndarray | None = None

    # Stage 3
    diff_score: np.ndarray | None = None
    regions: list[RegionFinding] = field(default_factory=list)

    # Control flow. A stage sets this to stop the pipeline; the verdict stage
    # reads it. Nothing else may.
    halt_verdict: str | None = None
    halt_reason: str = ""

    # Verdict
    verdict: str | None = None
    confidence: float = 0.0

    @property
    def halted(self) -> bool:
        return self.halt_verdict is not None

    def halt(self, verdict: str, reason: str) -> None:
        self.halt_verdict = verdict
        self.halt_reason = reason


@dataclass
class ComparisonResult:
    """One pair, end to end."""

    verdict: str
    confidence: float
    regions: list[RegionFinding]
    traces: list[Any]                          # list[StageTrace]
    duration_ms: float
    reference_sha256: str
    marketplace_sha256: str
    error: str | None = None

    @property
    def worst_severity(self) -> str:
        if not self.regions:
            return NONE
        return max((r.severity for r in self.regions),
                   key=lambda s: SEVERITY_RANK.get(s, 0))
