"""Typed pipeline configuration.

Carried over from the version-identification build's `core/config.py`: values are
grouped by the stage that consumes them, validated on construction, and readable
in both a nested and a flat shape. The flat shape is what `tools.calibrate` writes
and what every comparison freezes into `config_json`, so reproducing a past
comparison's verdict depends on it being a supported input forever.

The thresholds that matter here are **not** the ones from the other build. That
build compares re-encoded copies of one file; this one compares images that may
have a camera between them. The noise floor is a different distribution and has to
be measured again — `tools.calibrate` does that, and until it has run these
defaults are placeholders that say so via `calibrated=False`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field

from .paths import CONFIG_PATH


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NormalizeConfig(_Section):
    """Stage 0. Identical to the other build — the marketplace does the same
    things to an image whichever question you are asking about it."""

    # Mean-absolute-deviation cutoff for calling a row or column uniform.
    border_uniform_tolerance: float = Field(default=10.0, gt=0)
    # Never strip more than this per side, whatever the scan claims.
    max_border_crop_fraction: float = Field(default=0.30, gt=0, lt=0.5)


class RegistrationConfig(_Section):
    """Stage 2. Rejection is on *quality*, not merely on failure to converge.

    A homography that converged on 18 inliers spread over one corner of the frame
    is worse than no homography at all, because everything downstream will treat
    its output as aligned.
    """

    max_features: int = Field(default=6000, ge=200)
    # Below this many SIFT keypoints on either side, fall back to the binary
    # detector: SIFT starves on flat, low-texture packaging.
    min_sift_keypoints: int = Field(default=100, ge=0)
    lowe_ratio: float = Field(default=0.75, gt=0, lt=1)
    ransac_reproj_px: float = Field(default=3.0, gt=0)
    # Enough inliers to trust the transform.
    inliers_ok: int = Field(default=30, ge=1)
    # Below this, stop the pipeline: nothing downstream is meaningful.
    inliers_required: int = Field(default=15, ge=1)
    # A near-degenerate homography maps the whole reference onto a line.
    max_condition_number: float = Field(default=1e6, gt=1)
    min_scale: float = Field(default=0.25, gt=0)
    max_scale: float = Field(default=4.0, gt=0)
    # The warped reference must actually cover the marketplace frame; a 10%
    # overlap means the two images share a corner, not a product.
    min_overlap_fraction: float = Field(default=0.30, gt=0, le=1)


class StructuralDiffConfig(_Section):
    """Stage 3. **Tuned for recall, not precision.**

    Its output is candidate regions for OCR, not findings. A false region costs
    one OCR call; a missed region is invisible forever. The threshold sits at
    roughly the 95th percentile of the calibrated noise floor rather than the
    99.9th, which is the opposite of the tuning philosophy at this stage in the
    version-identification build, and deliberately so.
    """

    # Odd, and small enough that a changed digit is not averaged away.
    ssim_window: int = Field(default=7, ge=3)
    # `(1 - ssim)/2` at the noise floor. Calibrated.
    ssim_threshold: float = Field(default=0.30, gt=0, le=1)
    # A pure palette change moves chroma while barely moving luma, so chroma is
    # compared separately. This was a real bug in the other build, found and
    # fixed once already; it is not reintroduced here.
    chroma_threshold: float = Field(default=12.0, gt=0)
    # Kill speckle.
    morph_open: int = Field(default=3, ge=1)
    # **Anisotropic on purpose.** The diff proposes where pixels changed; OCR
    # needs whole text lines. Those are different units, and a box that clips a
    # word mid-glyph produces a garbage reading and therefore a false finding —
    # measured: an unchanged pack read as "hoco" against "Choco". A wide, short
    # closing kernel merges the fragments of one line into one region without
    # bridging the line above it.
    morph_close_x: int = Field(default=31, ge=1)
    morph_close_y: int = Field(default=7, ge=1)
    # 0.05% of the overlap. The other build needed an order of magnitude less
    # (§14 of its TECHNICAL.md) because its regions are per-digit and its
    # reference-vs-reference diffs are noise-free. Here regions are merged to
    # line level and the noise floor is far higher, so the spec's own figure is
    # the right one — and it is what excludes the artwork's trim ticks, which
    # otherwise propose a dozen junk regions along every edge.
    min_region_area_fraction: float = Field(default=0.0005, gt=0, lt=1)
    # A cap, not a filter: a warped photograph can propose hundreds of regions,
    # and OCR-ing all of them buys nothing. Largest-first, so the cap drops the
    # least significant.
    max_regions: int = Field(default=25, ge=1)
    # Erode the valid-overlap mask before differencing. This does two jobs: the
    # warp interpolates along the overlap boundary, and the de-padding boundary
    # is only ever located to about a pixel. Neither is a change in the artwork.
    overlap_erode_px: int = Field(default=8, ge=0)

    # -- global recolour ---------------------------------------------------
    # A hue rotation moves chroma across the whole pack while leaving the luma
    # structure — the text — intact. Decomposed into components it reads as
    # fifty separate findings, which is technically accurate and useless. When
    # the change is both large and chroma-dominated it collapses to one region
    # meaning "the palette moved", and structural changes are then taken from
    # the luma channel alone so a recolour cannot mask a changed number.
    # Reach across the frame, measured as the union bounding box of the changed
    # components — not their area. Only the saturated parts of a pack clear the
    # threshold under a hue rotation, so a recolour's area can be modest while
    # its spread is total.
    global_change_area_fraction: float = Field(default=0.40, gt=0, le=1)
    global_change_min_regions: int = Field(default=10, ge=2)
    # Separates a repainted pack from a photograph under a warm lamp: both are
    # chroma-dominant and both reach across the frame, but only the recolour
    # pushes a large *area* past the threshold.
    global_change_min_area_fraction: float = Field(default=0.02, gt=0, le=1)
    chroma_dominance_fraction: float = Field(default=0.75, gt=0, le=1)


class OcrConfig(_Section):
    """Stage 4. The decider.

    A 300-pixel delta at 0.013% of frame is ambiguous. `"450mg"` versus `"480mg"`
    is not. Everything here exists to make the second reading trustworthy.
    """

    backend: str = Field(default="auto")
    # OCR degrades badly on tight crops.
    crop_pad_fraction: float = Field(default=0.10, ge=0, le=1)
    # Horizontal crop padding, in line heights, and a genuine trade in both
    # directions rather than a value to maximise.
    #
    # Too small and the crop clips the glyph the region caught only half of.
    # Measured on a REENCODED pair whose region clipped the F of "Flakes": at
    # 1.2 the reference read "lakes" against the marketplace's "Flakes", which
    # the ladder calls TEXT_CHANGED — unchanged artwork reported as DIFFERENT,
    # the one failure this build treats as unacceptable.
    #
    # Too large and the crop reaches into the *neighbouring* word and returns a
    # fragment of it. Fragments are worse than they look: they are tokens, so
    # they shift the alignment in stage 5. Measured on a CLAIM_REMOVED pair at
    # 1.8, "Vegan No palm oil" against "No palm oil" was read as "gar Vegan No
    # palm oil" against "igar No palm oil", and difflib then paired the fragment
    # with the removed word into one `replace` opcode instead of reporting a
    # removal at all. A removed claim came back MATCH.
    #
    # Measured over 120 pairs: 1.2 misses 23 real changes, 1.4 misses 25, 1.8
    # misses 26 — but 1.2 is the one that produces the false positive above.
    # 1.4 is the smallest value that does not.
    crop_pad_line_heights: float = Field(default=1.4, gt=0)
    # **The detector's own resize cap, and the largest single cost in the
    # pipeline.** PP-OCR ships `limit_type: min, limit_side_len: 736`, which
    # rescales every image so its *shortest* side is 736 — a 244x78 region crop
    # is therefore blown up to 2325x736 before detection runs. Measured on real
    # region crops: 449ms each, and the upscale smears decimal points into
    # separate tokens ("27. 7.5" for "27.5"), which reads downstream as a token
    # the marketplace added and therefore as a material change. Capping the
    # *longest* side instead leaves a crop at its own resolution and only
    # downscales genuinely large ones: 54ms each, and the numbers read correctly.
    det_limit_side_len: int = Field(default=960, ge=64)
    # A white margin added around the crop immediately before reading, and not
    # to the crop artefact the UI shows. DBNet is trained on document scans,
    # which have margins; a glyph flush against the image edge is treated as a
    # partial glyph. Widening the crop instead pulls in neighbouring artwork,
    # which is a different fix for a different problem — this one is a quiet
    # zone, not more context.
    quiet_zone_px: int = Field(default=24, ge=0)
    # Small-text recognition improves substantially with upscaling, and cost is
    # irrelevant at one pair at a time. Kept after the detector cap above turned
    # the double upscale (ours, then the detector's) into a single one.
    min_long_edge: int = Field(default=300, ge=1)
    upscale_max: float = Field(default=3.0, ge=1)
    # The second, differently-scaled read used for self-calibration. Any value
    # other than 1.0 works; 1.6 is far enough to expose an unstable reading and
    # close enough not to manufacture one.
    consistency_scale: float = Field(default=1.6, gt=0)
    # Tokens read less confidently than this are kept but marked, and a region
    # containing one cannot produce a positive finding on its own.
    min_token_confidence: float = Field(default=0.55, ge=0, le=1)
    # When one side reads text and the other reads nothing, this is the share of
    # the reference crop's edge detail the marketplace crop must have *lost* for
    # the difference to count as a removal. Above this ratio the ink is still
    # there and the reader simply missed it, so the region is marked unreliable.
    asymmetric_ink_ratio: float = Field(default=0.55, gt=0, le=2)


class TextCompareConfig(_Section):
    """Stage 5. Classification is by **type**, never by string equality."""

    # `450` and `450.0` must not fire. Compared as numbers, with a relative
    # tolerance for the float formatting marketplaces apply.
    numeric_relative_tolerance: float = Field(default=1e-9, ge=0)
    # Edit distance at or under this, over confusable characters only, routes to
    # UNCERTAIN rather than MATERIAL.
    confusable_max_distance: int = Field(default=1, ge=0)
    # In a region the reader could not read consistently, two readings at least
    # this similar are treated as the same text badly read, rather than as a
    # difference needing review.
    unreliable_similarity: float = Field(default=0.75, gt=0, le=1)


_FLAT_MAP: dict[str, tuple[str, str]] = {
    "border_uniform_tolerance": ("normalize", "border_uniform_tolerance"),
    "max_border_crop_fraction": ("normalize", "max_border_crop_fraction"),
    "registration_max_features": ("registration", "max_features"),
    "registration_min_sift_keypoints": ("registration", "min_sift_keypoints"),
    "registration_lowe_ratio": ("registration", "lowe_ratio"),
    "registration_ransac_reproj_px": ("registration", "ransac_reproj_px"),
    "registration_inliers_ok": ("registration", "inliers_ok"),
    "registration_inliers_required": ("registration", "inliers_required"),
    "registration_max_condition_number": ("registration", "max_condition_number"),
    "registration_min_scale": ("registration", "min_scale"),
    "registration_max_scale": ("registration", "max_scale"),
    "registration_min_overlap_fraction": ("registration", "min_overlap_fraction"),
    "ssim_window": ("diff", "ssim_window"),
    "ssim_threshold": ("diff", "ssim_threshold"),
    "chroma_threshold": ("diff", "chroma_threshold"),
    "morph_open": ("diff", "morph_open"),
    "morph_close_x": ("diff", "morph_close_x"),
    "morph_close_y": ("diff", "morph_close_y"),
    "min_region_area_fraction": ("diff", "min_region_area_fraction"),
    "max_regions": ("diff", "max_regions"),
    "overlap_erode_px": ("diff", "overlap_erode_px"),
    "global_change_area_fraction": ("diff", "global_change_area_fraction"),
    "global_change_min_regions": ("diff", "global_change_min_regions"),
    "global_change_min_area_fraction": ("diff", "global_change_min_area_fraction"),
    "chroma_dominance_fraction": ("diff", "chroma_dominance_fraction"),
    "ocr_backend": ("ocr", "backend"),
    "ocr_crop_pad_fraction": ("ocr", "crop_pad_fraction"),
    "ocr_crop_pad_line_heights": ("ocr", "crop_pad_line_heights"),
    "ocr_det_limit_side_len": ("ocr", "det_limit_side_len"),
    "ocr_quiet_zone_px": ("ocr", "quiet_zone_px"),
    "ocr_min_long_edge": ("ocr", "min_long_edge"),
    "ocr_upscale_max": ("ocr", "upscale_max"),
    "ocr_consistency_scale": ("ocr", "consistency_scale"),
    "ocr_min_token_confidence": ("ocr", "min_token_confidence"),
    "ocr_asymmetric_ink_ratio": ("ocr", "asymmetric_ink_ratio"),
    "numeric_relative_tolerance": ("text", "numeric_relative_tolerance"),
    "confusable_max_distance": ("text", "confusable_max_distance"),
    "unreliable_similarity": ("text", "unreliable_similarity"),
}

# Keys the API will accept a `PUT` for. Everything else is structural: changing
# it invalidates the calibration rather than adjusting it.
EDITABLE: frozenset[str] = frozenset({
    "ssim_threshold",
    "chroma_threshold",
    "min_region_area_fraction",
    "registration_inliers_ok",
    "registration_inliers_required",
    "registration_lowe_ratio",
    "registration_min_overlap_fraction",
    "ocr_min_token_confidence",
    "morph_open",
    "morph_close",
    "max_regions",
})


class EngineConfig(BaseModel):
    """The fully resolved configuration a comparison freezes and reproduces from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    normalize: NormalizeConfig = NormalizeConfig()
    registration: RegistrationConfig = RegistrationConfig()
    diff: StructuralDiffConfig = StructuralDiffConfig()
    ocr: OcrConfig = OcrConfig()
    text: TextCompareConfig = TextCompareConfig()

    # False until `tools.calibrate` has run. Thresholds are a property of the
    # image pipeline and are meant to be measured; defaults are a placeholder.
    calibrated: bool = False
    # Anything else the file carried — the `calibration` metadata block, keys
    # written by a newer version. Preserved so a round-trip is lossless.
    extra: dict[str, Any] = Field(default_factory=dict)

    # -- flat interop ------------------------------------------------------

    @classmethod
    def from_flat(cls, flat: dict[str, Any]) -> "EngineConfig":
        sections: dict[str, dict[str, Any]] = {}
        extra: dict[str, Any] = {}
        calibrated = False

        for key, value in flat.items():
            if key == "calibrated":
                calibrated = bool(value)
                continue
            target = _FLAT_MAP.get(key)
            if target is None:
                extra[key] = value
                continue
            section, field_name = target
            sections.setdefault(section, {})[field_name] = value

        return cls(calibrated=calibrated, extra=extra, **sections)

    def to_flat(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, (section, field_name) in _FLAT_MAP.items():
            value = getattr(getattr(self, section), field_name)
            if value is not None:
                out[key] = value
        out["calibrated"] = self.calibrated
        out.update(self.extra)
        return out

    def with_flat(self, updates: dict[str, Any]) -> "EngineConfig":
        flat = self.to_flat()
        flat.update(updates)
        return EngineConfig.from_flat(flat)

    # -- mapping surface ----------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        flat = self.to_flat()
        if key not in flat:
            raise KeyError(key)
        return flat[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_flat().get(key, default)

    def keys(self) -> Iterator[str]:
        return iter(self.to_flat())


def load_config(path: Path | None = None) -> EngineConfig:
    """Read the calibrated configuration, falling back to placeholder defaults."""
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return EngineConfig()
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        return EngineConfig()
    return EngineConfig.from_flat(raw)


def save_config(cfg: EngineConfig, path: Path | None = None) -> Path:
    p = Path(path) if path else CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg.to_flat(), indent=2, sort_keys=True) + "\n")
    return p


def config_from_json(config_json: str) -> EngineConfig:
    """Rebuild the exact configuration a stored comparison used."""
    return EngineConfig.from_flat(json.loads(config_json or "{}"))
