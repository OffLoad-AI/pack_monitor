"""PaddleOCR backend.

Preferred when installed, since it is what the spec names. Kept behind the same
interface as `rapid.py` so nothing above this module knows which one is running —
the engine's identity is reported in the trace and nowhere else.
"""

from __future__ import annotations

import threading

import numpy as np

from ..types import OcrReading, OcrToken
from .base import clean_tokens, order_tokens


class PaddleOcr:
    name = "paddleocr"
    available = True

    def __init__(self) -> None:
        from paddleocr import PaddleOCR

        self._engine = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
        self._lock = threading.Lock()

    def read(self, rgb: np.ndarray) -> OcrReading:
        if rgb is None or rgb.size == 0:
            return OcrReading(text="", tokens=[])
        try:
            with self._lock:
                result = self._engine.ocr(np.ascontiguousarray(rgb), cls=False)
        except Exception:  # noqa: BLE001 — an unreadable crop is empty, not fatal
            return OcrReading(text="", tokens=[])

        # PaddleOCR nests one list per input image.
        lines = (result or [[]])[0] or []
        tokens: list[OcrToken] = []
        for quad, (text, score) in lines:
            pts = np.asarray(quad, dtype=np.float32)
            x0, y0 = pts[:, 0].min(), pts[:, 1].min()
            x1, y1 = pts[:, 0].max(), pts[:, 1].max()
            tokens.append(OcrToken(
                text=str(text),
                confidence=float(score),
                box=(int(x0), int(y0), int(max(1, x1 - x0)), int(max(1, y1 - y0))),
            ))

        tokens = order_tokens(clean_tokens(tokens))
        return OcrReading(text=" ".join(t.text for t in tokens).strip(), tokens=tokens)
