"""One listing image, end to end.

Runs the engine, turns its answer into a compliance verdict, builds the reviewer's
change list, and renders the overlay. This is the whole per-image path; the code
around it only moves data and images.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from core.context import ImageStore
from core.engine import Engine
from core.types import CandidateSet, Probe

from . import verdict as V
from .deltas import build_deltas
from .overlay import write_diff_overlay
from .registry import current_candidate, resolve_within_group


def _blank_result(source_path: str, product_id: str, sha: str,
                  current_id: int | None) -> dict[str, Any]:
    return {
        "source_path": source_path, "product_id": product_id, "sha256": sha,
        "width": 0, "height": 0, "verdict": V.ERROR, "matched_version_id": None,
        "current_version_id": current_id, "match_method": "NONE",
        "confidence": 0.0, "regions": [], "severity": "UNCERTAIN",
        "diff_map_path": None, "error": None, "cached": False,
        "trace": [],
    }


def identify_listing(engine: Engine, source_path: str, sha: str,
                     cset: CandidateSet, store: ImageStore | None = None,
                     diff_dir: Path | None = None) -> dict[str, Any]:
    """Identify one listing image and decide what it means.

    Returns a plain dict so it can cross a process boundary without the persistence
    layer needing any of the engine's types.
    """
    current = current_candidate(cset)
    result = _blank_result(source_path, cset.key, sha, int(current.id))

    try:
        probe = Probe(path=Path(source_path), content_hash=sha)
        # Own the context so the normalized probe can be read back below without
        # decoding and de-padding the file a second time.
        ctx = engine.context(probe, cset, store)
        match = engine.run(ctx)

        result["trace"] = [
            {"stage": r.stage, "decisive": r.decisive, "matched_id": r.matched_id,
             "confidence": round(r.confidence, 6),
             "duration_ms": round(r.duration_ms, 3), "evidence": dict(r.evidence)}
            for r in match.trace
        ]

        if match.error is not None:
            result.update(verdict=V.ERROR, severity="UNCERTAIN",
                          error=match.error)
            return result

        # The hash stage deliberately never decodes the file, so on a hash match
        # nothing has been normalized and the dimensions come from the header.
        # Anything else already paid for the decode, memoized on the context.
        if match.method == "HASH_EXACT":
            normalized = None
            with Image.open(source_path) as im:
                result["width"], result["height"] = im.size
        else:
            normalized = ctx.normalized
            result["width"], result["height"] = normalized.raw_size

        if match.matched is None:
            result.update(verdict=V.UNKNOWN_IMAGE, severity="UNCERTAIN",
                          match_method="NONE", confidence=0.0)
            return result

        matched = resolve_within_group(cset, match.matched, current)
        deltas = build_deltas(cset, matched, current, normalized)
        vd, severity = V.decide(_Ident(matched), _Ident(current), deltas)

        result.update(
            matched_version_id=int(matched.id),
            match_method=match.method,
            confidence=round(match.confidence, 6),
            verdict=vd, severity=severity, regions=deltas,
        )

        if vd == V.STALE_VERSION and deltas and diff_dir is not None:
            out = diff_dir / f"{sha[:16]}__{cset.key}.jpg"
            result["diff_map_path"] = write_diff_overlay(source_path, deltas, out)

        return result

    except Exception as exc:  # noqa: BLE001 - one bad file must not sink a run
        result.update(verdict=V.ERROR, severity="UNCERTAIN",
                      error=f"{type(exc).__name__}: {exc}")
        return result


class _Ident:
    """Adapts a Candidate to the `.id` / `.sha256` pair `verdict.decide` compares."""

    __slots__ = ("id", "sha256")

    def __init__(self, candidate):
        self.id = candidate.id
        self.sha256 = candidate.content_hash
