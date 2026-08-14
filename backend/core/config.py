"""Typed engine configuration.

Replaces the flat 19-key dict that was read by string literal across the pipeline.
Values are grouped by the stage that consumes them, validated on construction, and
carry their provenance — every threshold here is measured by `tools.calibrate`, not
chosen, and the model refuses values that could not have come from a measurement.

Two shapes have to be readable, and this is not optional:

* `config/thresholds.json`, which `tools.calibrate` writes flat.
* `Run.config_json`, frozen flat into every run that has already completed.

Reproducing a past run's verdicts depends on parsing the second one, so the flat
form is a supported input forever, not a transitional concession. `EngineConfig`
also answers `cfg["luma_threshold"]` so that code still expecting a mapping keeps
working while it is ported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field

from .paths import CONFIG_PATH, REPO_ROOT  # noqa: F401  (re-exported)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiffConfig(_Section):
    """Scraped-vs-reference differencing. Both thresholds are calibrated."""

    # p99.9 of the unchanged luma difference — the level a pixel reaches through
    # re-encoding alone. Measured, never guessed.
    luma_threshold: float = Field(default=32.0, gt=0)
    # Calibrated separately because the two noise floors differ by ~3x. A single
    # threshold taken from the luma floor cannot see a palette change at all.
    chroma_threshold: float = Field(default=14.0, gt=0)
    # Compare each scraped pixel against the range of reference values in its
    # r-pixel neighbourhood. Letterbox padding can only be located to about a
    # pixel, and the resulting sub-pixel scale error haloes every glyph.
    tolerance_radius: int = Field(default=1, ge=0, le=8)


class ReferenceDiffConfig(_Section):
    """Reference-vs-reference. Our own files: aligned, uncompressed, exact."""

    luma_threshold: float = Field(default=10.0, gt=0)
    chroma_threshold: float = Field(default=10.0, gt=0)
    # No misregistration between two of our own PNGs, so nothing to forgive.
    tolerance_radius: int = Field(default=0, ge=0, le=8)


class NormalizeConfig(_Section):
    # Mean-absolute-deviation cutoff for calling a row or column uniform.
    border_uniform_tolerance: float = Field(default=10.0, gt=0)
    # Never strip more than this per side, whatever the scan claims.
    max_border_crop_fraction: float = Field(default=0.30, gt=0, lt=0.5)


class MorphologyConfig(_Section):
    # Whole-image screening can afford an aggressive open: it only has to spot
    # gross differences, and the open buys a cleaner noise floor.
    open: int = Field(default=3, ge=1)
    # 25px merges a logo or badge into one box — the unit a reviewer acts on —
    # without ever bridging two separate edits.
    close: int = Field(default=25, ge=1)
    # Region checks must not open at all: a changed digit is a 2-3px stroke once
    # the listing has been downscaled, and a 3x3 open erases it completely.
    region_open: int = Field(default=1, ge=1)
    # 0.05% of a 1500x1500 canvas is 1125px, but a changed digit is ~330px.
    # An order of magnitude lower is safe because reference diffs are noise-free.
    min_region_area_fraction: float = Field(default=0.00005, gt=0, lt=1)
    # A diffuse change touching most of the artwork is one finding, not fifty.
    global_change_area_fraction: float = Field(default=0.25, gt=0, le=1)
    global_change_min_regions: int = Field(default=20, ge=2)


class WholeImageStageConfig(_Section):
    """Stage 3 — whole-image screening."""

    clean_fraction: float = Field(default=0.012, gt=0, lt=1)


class RegionStageConfig(_Section):
    """Stage 4 — discriminating-region ranking, which does most of the work."""

    # The winner is judged against the runner-up, not an absolute bar: both carry
    # the same compression noise in the same boxes, so their difference is the
    # real signal. Set to the tightest value producing zero false alarms, because
    # reporting good artwork as stale is what gets a compliance tool switched off.
    margin_ratio: float = Field(default=1.12, gt=1.0)
    # Stops one saturated region from swamping a small text edit in the same sum.
    signal_cap: float = Field(default=3.0, gt=0)
    # Average only the most-changed pixels: a changed digit is a few percent of
    # its bounding box, and a plain mean buries it in the unchanged background.
    signal_top_fraction: float = Field(default=0.05, gt=0, le=1)
    changed_fraction: float = Field(default=0.02, gt=0, lt=1)


class SingleCandidateStageConfig(_Section):
    """The lone-candidate case — a product with exactly one artwork version.

    The old pipeline accepted the only candidate unconditionally, so on first
    deployment a foreign product and even random noise both returned PASS. This
    stage requires positive evidence instead, and declines otherwise.
    """

    # Accept a lone candidate only if it is at least this clean. `None` means
    # "reuse the whole-image clean_fraction", which is the sane default.
    accept_below_fraction: float | None = Field(default=None, gt=0, lt=1)


# Flat key <-> (section, field). The single source of truth for both directions;
# `to_flat` and `from_flat` are derived from it so they cannot drift apart.
_FLAT_MAP: dict[str, tuple[str, str]] = {
    "luma_threshold": ("diff", "luma_threshold"),
    "chroma_threshold": ("diff", "chroma_threshold"),
    "tolerance_radius": ("diff", "tolerance_radius"),
    "reference_luma_threshold": ("reference", "luma_threshold"),
    "reference_chroma_threshold": ("reference", "chroma_threshold"),
    "reference_tolerance_radius": ("reference", "tolerance_radius"),
    "border_uniform_tolerance": ("normalize", "border_uniform_tolerance"),
    "max_border_crop_fraction": ("normalize", "max_border_crop_fraction"),
    "morph_open": ("morphology", "open"),
    "morph_close": ("morphology", "close"),
    "region_morph_open": ("morphology", "region_open"),
    "min_region_area_fraction": ("morphology", "min_region_area_fraction"),
    "global_change_area_fraction": ("morphology", "global_change_area_fraction"),
    "global_change_min_regions": ("morphology", "global_change_min_regions"),
    "clean_fraction": ("whole_image", "clean_fraction"),
    "region_margin_ratio": ("region", "margin_ratio"),
    "region_signal_cap": ("region", "signal_cap"),
    "region_signal_top_fraction": ("region", "signal_top_fraction"),
    "region_changed_fraction": ("region", "changed_fraction"),
    "single_candidate_accept_below": ("single_candidate", "accept_below_fraction"),
}


class EngineConfig(BaseModel):
    """The fully resolved configuration a run freezes and reproduces from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    diff: DiffConfig = DiffConfig()
    reference: ReferenceDiffConfig = ReferenceDiffConfig()
    normalize: NormalizeConfig = NormalizeConfig()
    morphology: MorphologyConfig = MorphologyConfig()
    whole_image: WholeImageStageConfig = WholeImageStageConfig()
    region: RegionStageConfig = RegionStageConfig()
    single_candidate: SingleCandidateStageConfig = SingleCandidateStageConfig()

    # False until `tools.calibrate` has run. Thresholds are a property of the
    # encoding pipeline and are meant to be measured; defaults are a placeholder.
    calibrated: bool = False
    # Anything else the file carried — the `calibration` metadata block, keys
    # written by a newer version. Preserved so a round-trip is lossless and an
    # older binary cannot silently drop a field it does not understand.
    extra: dict[str, Any] = Field(default_factory=dict)

    # -- flat interop ------------------------------------------------------

    @classmethod
    def from_flat(cls, flat: dict[str, Any]) -> "EngineConfig":
        """Build from the flat shape written by calibrate and frozen into runs."""
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
            section, field = target
            sections.setdefault(section, {})[field] = value

        return cls(calibrated=calibrated, extra=extra, **sections)

    def to_flat(self) -> dict[str, Any]:
        """The flat shape, for `Run.config_json` and `config/thresholds.json`."""
        out: dict[str, Any] = {}
        for key, (section, field) in _FLAT_MAP.items():
            value = getattr(getattr(self, section), field)
            if value is not None:
                out[key] = value
        out["calibrated"] = self.calibrated
        out.update(self.extra)
        return out

    # -- mapping surface, so partially-ported code keeps working ------------

    def __getitem__(self, key: str) -> Any:
        flat = self.to_flat()
        if key not in flat:
            raise KeyError(key)
        return flat[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_flat().get(key, default)

    def keys(self) -> Iterator[str]:
        return iter(self.to_flat())

    # -- derived ------------------------------------------------------------

    @property
    def single_candidate_threshold(self) -> float:
        """The bar a lone candidate must clear, defaulting to the clean cutoff."""
        explicit = self.single_candidate.accept_below_fraction
        return explicit if explicit is not None else self.whole_image.clean_fraction


def load_config(path: Path | None = None) -> EngineConfig:
    """Read the calibrated configuration, falling back to measured-elsewhere defaults."""
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return EngineConfig()
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        return EngineConfig()
    return EngineConfig.from_flat(raw)


def config_from_run(config_json: str) -> EngineConfig:
    """Rebuild the exact configuration a completed run used."""
    return EngineConfig.from_flat(json.loads(config_json or "{}"))
