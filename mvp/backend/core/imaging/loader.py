"""Decoding and hashing.

Every function here is a pure function of the input bytes. Nondeterminism at this
layer would surface as a report that flags different things on different runs over
unchanged inputs, which is the fastest way to lose a reviewer's trust.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageCms

Image.MAX_IMAGE_PIXELS = None

_SRGB = ImageCms.createProfile("sRGB")


def sha256_file(path: str | Path) -> str:
    """Hash the raw file bytes, never decoded pixels.

    Decoding depends on library versions, so a pixel hash would not be stable
    across environments — and stability is the entire point of the hash stage.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_rgb(path: str | Path) -> np.ndarray:
    """Decode to an H x W x 3 uint8 RGB array.

    Alpha is composited onto white, matching what a marketplace does when it
    flattens a transparent PNG, and an ICC profile is converted to sRGB so two
    copies of one file in different colour spaces still compare equal.
    """
    with Image.open(path) as im:
        im.load()

        icc = im.info.get("icc_profile")
        if icc and im.mode in ("RGB", "RGBA"):
            try:
                src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                im = ImageCms.profileToProfile(im, src, _SRGB, outputMode=im.mode)
            except Exception:
                # A malformed profile is not a reason to fail the image.
                pass

        if im.mode == "P":
            im = im.convert("RGBA")
        if im.mode in ("RGBA", "LA"):
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im.convert("RGBA"))
        im = im.convert("RGB")
        return np.asarray(im, dtype=np.uint8)


def to_ycrcb(img: np.ndarray) -> np.ndarray:
    """Split into luma and chroma, which carry different noise and are thresholded
    separately — their floors differ by roughly a factor of three."""
    return cv2.cvtColor(img, cv2.COLOR_RGB2YCrCb)
