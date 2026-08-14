"""The OCR interface, and the honest fallback.

`read()` returns tokens in reading order with their own confidences. Confidences
per token rather than per crop matters: one badly-read character in an otherwise
clean line is the difference between a material finding and an OCR artefact, and
a single crop-level number cannot express that.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from ..types import OcrReading


@runtime_checkable
class OcrEngine(Protocol):
    name: str
    available: bool

    def read(self, rgb: np.ndarray) -> OcrReading:
        """Read one crop. Never raises — an unreadable crop is empty, not fatal."""
        ...


class NullOcr:
    """No OCR installed.

    Returns empty readings *and* advertises `available = False`, which the region
    stage turns into `ocr_unreliable` on every region. That routes every text
    difference to `UNCERTAIN`. The alternative — returning empty strings from a
    working-looking engine — would make every region read as "no text on either
    side", i.e. `VISUAL_ONLY`, which is a confident claim this installation has no
    basis for.
    """

    name = "none"
    available = False

    def read(self, rgb: np.ndarray) -> OcrReading:  # noqa: ARG002
        return OcrReading(text="", tokens=[])


def clean_tokens(tokens):
    """Drop tokens with no ASCII letter or digit in them.

    A recognizer handed a crop of a *graphic* — a certification mark, a logo —
    does not return nothing. It returns its best guess at what those shapes spell,
    which on a circular organic mark is something like `O 了`. Left in, that turns
    a region with no text into a region whose text apparently changed, and the
    `VISUAL_ONLY` path that exists for exactly these regions never runs.
    """
    return [t for t in tokens if any(c.isascii() and c.isalnum() for c in t.text)]


def alphanumeric_count(text: str) -> int:
    return sum(1 for c in text if c.isascii() and c.isalnum())


def order_tokens(tokens):
    """Sort tokens into reading order: rows top-to-bottom, then left-to-right.

    OCR engines return detections in their own detection order, which is not
    reading order. Two crops read in different orders would then produce a
    spurious "words reordered" difference. Rows are banded by a fraction of the
    median token height so that a line whose glyphs sit a few pixels apart
    vertically still reads as one line.
    """
    if not tokens:
        return []
    heights = [max(1, t.box[3]) for t in tokens]
    band = max(1.0, float(np.median(heights)) * 0.6)
    return sorted(tokens, key=lambda t: (round(t.box[1] / band), t.box[0]))
