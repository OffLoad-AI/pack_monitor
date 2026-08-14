"""OCR backends.

The pixel stage cannot reliably separate a one-digit edit from compression noise
— the signal is genuinely below the noise floor and there is no trick available to
lift it out. So the pixel stage becomes a generous *proposer* and OCR becomes the
*decider*: a 300-pixel delta at 0.013% of frame is ambiguous, `"450mg"` versus
`"480mg"` is not.

Which engine does the reading is an implementation detail, so it sits behind one
interface with three implementations and an explicit `available` flag. A missing
engine must degrade to `UNCERTAIN` rather than to a confident wrong answer, which
is why `NullOcr` exists and why it reports itself as unavailable rather than
returning empty strings that would read as "no text here".
"""

from __future__ import annotations

from .base import NullOcr, OcrEngine

_ENGINE: OcrEngine | None = None


def available_backends() -> list[str]:
    """Which engines this installation could actually use, best first."""
    found = []
    for name, probe in (("paddleocr", _try_paddle), ("rapidocr", _try_rapid)):
        try:
            if probe(probe_only=True):
                found.append(name)
        except Exception:  # noqa: BLE001 - probing must never raise
            pass
    found.append("none")
    return found


def get_engine(name: str = "auto", det_limit_side_len: int = 960) -> OcrEngine:
    """Resolve and cache the OCR engine.

    Cached because model load is the dominant cost — around a second for
    RapidOCR — and a comparison reads a dozen crops. The detector's resize cap
    is a construction parameter rather than a per-read one, so a change to it
    has to rebuild the session; the cache key covers it.
    """
    global _ENGINE
    if _ENGINE is not None and (name == "auto" or _ENGINE.name == name) \
            and getattr(_ENGINE, "det_limit_side_len", det_limit_side_len) \
            == det_limit_side_len:
        return _ENGINE

    if name in ("auto", "paddleocr"):
        engine = _try_paddle()
        if engine is not None:
            _ENGINE = engine
            return engine
        if name == "paddleocr":
            raise RuntimeError("paddleocr backend requested but not installed")

    if name in ("auto", "rapidocr"):
        engine = _try_rapid(det_limit_side_len=det_limit_side_len)
        if engine is not None:
            _ENGINE = engine
            return engine
        if name == "rapidocr":
            raise RuntimeError("rapidocr backend requested but not installed")

    _ENGINE = NullOcr()
    return _ENGINE


def reset_engine() -> None:
    """Drop the cached engine — used by tests that switch backends."""
    global _ENGINE
    _ENGINE = None


def _try_paddle(probe_only: bool = False):
    import importlib.util

    if importlib.util.find_spec("paddleocr") is None:
        return None
    if probe_only:
        return True
    from .paddle import PaddleOcr

    return PaddleOcr()


def _try_rapid(probe_only: bool = False, det_limit_side_len: int = 960):
    import importlib.util

    if importlib.util.find_spec("rapidocr_onnxruntime") is None:
        return None
    if probe_only:
        return True
    from .rapid import RapidOcr

    return RapidOcr(det_limit_side_len=det_limit_side_len)


__all__ = ["OcrEngine", "NullOcr", "get_engine", "reset_engine", "available_backends"]
