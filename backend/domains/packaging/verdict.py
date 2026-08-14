"""Identification -> compliance verdict.

The engine answers "which approved artwork is this listing serving?". This turns
that into "and is that a problem?", which is a question only the packaging domain
can answer.
"""

from __future__ import annotations

import hashlib

# Ranked worst-first so `max_severity` can pick without a lookup table per call.
SEVERITY_RANK = {"NONE": 0, "COSMETIC": 1, "UNKNOWN": 2, "UNCERTAIN": 2, "MATERIAL": 3}
RANK_SEVERITY = {0: "NONE", 1: "COSMETIC", 2: "UNCERTAIN", 3: "MATERIAL"}

PASS = "PASS"
STALE_VERSION = "STALE_VERSION"
UNKNOWN_IMAGE = "UNKNOWN_IMAGE"
ERROR = "ERROR"


def max_severity(severities: list[str]) -> str:
    if not severities:
        return "NONE"
    return RANK_SEVERITY[max(SEVERITY_RANK.get(s, 2) for s in severities)]


def region_signature(product_id: str, x: int, y: int, w: int, h: int,
                     field_key: str | None) -> str:
    """Stable identity for a changed region, used to match acknowledgements.

    Coordinates are rounded to the nearest 10px so a detector box landing a few
    pixels differently on a re-run does not silently discard a reviewer's earlier
    sign-off. 10px absorbs detector jitter while staying far finer than the gap
    between two genuinely different edits.
    """
    payload = (f"{product_id}|{round(x, -1)}|{round(y, -1)}|"
               f"{round(w, -1)}|{round(h, -1)}|{field_key or ''}")
    return hashlib.sha256(payload.encode()).hexdigest()


def decide(matched_version, current_version, deltas: list[dict],
           error: bool = False) -> tuple[str, str]:
    """Return `(verdict, severity)`.

    Accepts anything with `.id` and `.sha256`, so it works with ORM rows and with
    the engine's candidates alike.
    """
    if error:
        return ERROR, "UNCERTAIN"
    if matched_version is None:
        return UNKNOWN_IMAGE, "UNCERTAIN"
    # Byte-identical artwork under a different label is still compliant artwork: a
    # version bump that did not change the pack is not a stale listing.
    if matched_version.id == current_version.id or \
            matched_version.sha256 == current_version.sha256:
        return PASS, "NONE"
    return STALE_VERSION, max_severity([d["severity"] for d in deltas])
