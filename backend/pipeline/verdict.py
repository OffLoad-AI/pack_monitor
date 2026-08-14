"""Compatibility shim — the implementation now lives in `domains.packaging.verdict`.

Deciding what an identification *means* is packaging-domain logic, not engine
logic, so it moved to the adapter. New code should import from there.
"""

from __future__ import annotations

from domains.packaging.verdict import (  # noqa: F401  (re-exported)
    ERROR,
    PASS,
    RANK_SEVERITY,
    SEVERITY_RANK,
    STALE_VERSION,
    UNKNOWN_IMAGE,
    decide,
    max_severity,
    region_signature,
)

__all__ = [
    "ERROR", "PASS", "RANK_SEVERITY", "SEVERITY_RANK", "STALE_VERSION",
    "UNKNOWN_IMAGE", "decide", "max_severity", "region_signature",
]
