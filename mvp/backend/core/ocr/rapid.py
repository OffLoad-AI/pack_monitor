"""RapidOCR backend — the PP-OCR models, run through ONNX Runtime.

The spec calls for PaddleOCR. This runs the same PP-OCR detection and recognition
models; it differs only in the runtime underneath them, and it installs in about
15MB rather than dragging in the full PaddlePaddle framework. `paddle.py` is the
same interface over PaddleOCR proper, and is picked first when it is installed.
"""

from __future__ import annotations

import threading

import numpy as np

from ..types import OcrReading, OcrToken
from .base import clean_tokens, order_tokens


class RapidOcr:
    name = "rapidocr"
    available = True

    def __init__(self, det_limit_side_len: int = 960) -> None:
        from rapidocr_onnxruntime import RapidOCR

        # `limit_type="max"` rather than the shipped default of `"min"`. The
        # default rescales every image so its *shortest* side reaches
        # `limit_side_len`, which on a region crop is an upscale of seven or
        # eight times before detection has run. Measured on this pipeline's own
        # crops: 449ms per crop against 54ms, and the default's upscale splits
        # "27.5" into the two tokens "27." and "7.5" — a token the marketplace
        # apparently added, which stage 5 classifies as a material change.
        self._engine = RapidOCR(det_limit_type="max",
                                det_limit_side_len=det_limit_side_len)
        self.det_limit_side_len = det_limit_side_len
        # Model inference is not guaranteed re-entrant, and the API runs
        # comparisons on a worker thread while serving requests on another.
        self._lock = threading.Lock()

    def read(self, rgb: np.ndarray) -> OcrReading:
        if rgb is None or rgb.size == 0:
            return OcrReading(text="", tokens=[])
        try:
            with self._lock:
                # `use_cls=False`: the angle classifier only decides 0 against
                # 180 degrees, and every crop reaching here has been through the
                # homography, so it is already upright. Measured at 37% of the
                # read cost for output identical on every crop tested.
                result, _elapsed = self._engine(np.ascontiguousarray(rgb),
                                                use_cls=False)
        except Exception:  # noqa: BLE001 — an unreadable crop is empty, not fatal
            return OcrReading(text="", tokens=[])

        tokens: list[OcrToken] = []
        for entry in result or []:
            quad, text, score = entry[0], entry[1], entry[2]
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
