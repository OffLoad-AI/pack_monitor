"""Configuration, calibration and health."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from core.config import EDITABLE, load_config, save_config
from core.ocr import available_backends, get_engine
from core.paths import CALIBRATION_DIR, PIPELINE_VERSION

from ..schemas import ConfigOut, ConfigUpdate

router = APIRouter(prefix="/api", tags=["system"])


def _config_out() -> ConfigOut:
    cfg = load_config()
    flat = cfg.to_flat()
    calibration = flat.pop("calibration", None)
    engine = get_engine(cfg.ocr.backend, cfg.ocr.det_limit_side_len)
    return ConfigOut(
        values={k: v for k, v in flat.items() if k != "calibrated"},
        editable=sorted(EDITABLE),
        calibrated=cfg.calibrated,
        calibration=calibration,
        ocr_backends=available_backends(),
        ocr_active=engine.name,
    )


@router.get("/config", response_model=ConfigOut)
def get_config() -> ConfigOut:
    return _config_out()


@router.put("/config", response_model=ConfigOut)
def update_config(payload: ConfigUpdate) -> ConfigOut:
    """Edit whitelisted thresholds, and mark the configuration as no longer measured.

    Everything outside the whitelist is structural: changing it does not adjust
    the calibration, it invalidates it. And editing anything at all sets
    `calibrated: false`, because a hand-set threshold is a judgement and the
    Settings screen should not go on presenting it as a measurement.
    """
    cfg = load_config()
    updates: dict[str, float] = {}

    for key, value in payload.values.items():
        if key not in EDITABLE:
            raise HTTPException(
                400, f"{key!r} cannot be edited here. Editable keys: "
                     f"{', '.join(sorted(EDITABLE))}.")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(400, f"{key!r} must be a number.")
        if value <= 0:
            raise HTTPException(400, f"{key!r} must be greater than zero.")
        updates[key] = value

    if not updates:
        raise HTTPException(400, "No values were supplied.")

    updates["calibrated"] = False
    save_config(cfg.with_flat(updates))
    return _config_out()


@router.get("/calibration")
def get_calibration() -> dict:
    """The measured distributions and the chart, so a number is never shown
    without the measurement it came from."""
    cfg = load_config()
    record = cfg.to_flat().get("calibration")
    chart = CALIBRATION_DIR / "noise_floor.png"
    return {
        "calibrated": cfg.calibrated,
        "record": record,
        "chart_url": "/calibration/noise_floor.png" if chart.exists() else None,
    }


@router.get("/health")
def health() -> dict:
    cfg = load_config()
    return {
        "status": "ok",
        "pipeline_version": PIPELINE_VERSION,
        "calibrated": cfg.calibrated,
        "ocr": get_engine(cfg.ocr.backend, cfg.ocr.det_limit_side_len).name,
    }
