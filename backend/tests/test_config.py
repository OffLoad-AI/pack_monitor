"""Configuration round-tripping.

Every completed run froze its thresholds as a flat JSON blob in `Run.config_json`,
and reproducing that run's verdicts means parsing it back exactly. The flat shape
is therefore a supported input permanently, not a migration step, and these tests
are what stop the typed model from quietly drifting away from it.
"""

from __future__ import annotations

import json

import pytest

from core.config import EngineConfig, config_from_run

# A real frozen configuration, as written by tools.calibrate and stored on a run.
FROZEN_RUN_CONFIG = {
    "border_uniform_tolerance": 10,
    "calibrated": True,
    "chroma_threshold": 29.0,
    "clean_fraction": 0.01748001,
    "global_change_area_fraction": 0.25,
    "global_change_min_regions": 20,
    "luma_threshold": 89.0,
    "max_border_crop_fraction": 0.3,
    "min_region_area_fraction": 5e-05,
    "morph_close": 25,
    "morph_open": 3,
    "reference_chroma_threshold": 10,
    "reference_luma_threshold": 10,
    "reference_tolerance_radius": 0,
    "region_changed_fraction": 0.005,
    "region_margin_ratio": 1.12,
    "region_morph_open": 1,
    "region_signal_cap": 3.0,
    "region_signal_top_fraction": 0.05,
    "tolerance_radius": 1,
}


def test_flat_config_round_trips_without_loss():
    cfg = EngineConfig.from_flat(FROZEN_RUN_CONFIG)
    out = cfg.to_flat()

    for key, value in FROZEN_RUN_CONFIG.items():
        assert key in out, f"{key} was dropped"
        assert out[key] == value, f"{key} changed: {value} -> {out[key]}"


def test_calibrated_values_land_in_the_right_sections():
    cfg = EngineConfig.from_flat(FROZEN_RUN_CONFIG)

    assert cfg.diff.luma_threshold == 89.0
    assert cfg.diff.chroma_threshold == 29.0
    assert cfg.reference.luma_threshold == 10
    assert cfg.whole_image.clean_fraction == 0.01748001
    assert cfg.region.margin_ratio == 1.12
    assert cfg.morphology.open == 3
    assert cfg.morphology.region_open == 1
    assert cfg.calibrated is True


def test_unknown_keys_survive_a_round_trip():
    """A newer writer's keys, and the calibration metadata block, must not vanish."""
    raw = dict(FROZEN_RUN_CONFIG)
    raw["calibration"] = {"image_pairs": 192, "luma": {"unchanged_p99_9": 89.0}}
    raw["some_future_key"] = 7

    out = EngineConfig.from_flat(raw).to_flat()

    assert out["calibration"] == raw["calibration"]
    assert out["some_future_key"] == 7


def test_config_from_run_parses_a_stored_blob():
    cfg = config_from_run(json.dumps(FROZEN_RUN_CONFIG))
    assert cfg.diff.luma_threshold == 89.0


def test_uncalibrated_defaults_are_marked_as_such():
    """Defaults are a placeholder; nothing should mistake them for measurements."""
    assert EngineConfig().calibrated is False


def test_mapping_access_still_works_for_unported_callers():
    cfg = EngineConfig.from_flat(FROZEN_RUN_CONFIG)

    assert cfg["luma_threshold"] == 89.0
    assert cfg.get("morph_close") == 25
    assert cfg.get("nonexistent", "fallback") == "fallback"
    with pytest.raises(KeyError):
        cfg["nonexistent"]


def test_single_candidate_threshold_defaults_to_the_clean_cutoff():
    """The lone-candidate bar reuses the screen's cutoff unless set explicitly."""
    cfg = EngineConfig.from_flat(FROZEN_RUN_CONFIG)
    assert cfg.single_candidate_threshold == cfg.whole_image.clean_fraction

    tightened = EngineConfig.from_flat(
        {**FROZEN_RUN_CONFIG, "single_candidate_accept_below": 0.001})
    assert tightened.single_candidate_threshold == 0.001


def test_implausible_values_are_rejected():
    """Thresholds are measurements; a negative or zero one is a bug, not a setting."""
    with pytest.raises(Exception):
        EngineConfig.from_flat({**FROZEN_RUN_CONFIG, "luma_threshold": -1})
    with pytest.raises(Exception):
        EngineConfig.from_flat({**FROZEN_RUN_CONFIG, "region_margin_ratio": 0.5})
