"""Response shapes.

Artefacts travel as **paths**, never as base64. The detail screen loads a dozen
images per comparison, several of them full pack fronts, and putting those
through the JSON layer would make every response megabytes and uncacheable. The
API mounts `data/` statically and hands back relative paths the browser fetches
normally.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StageOut(BaseModel):
    stage: str
    ordinal: int
    status: str
    confidence: float | None
    duration_ms: float
    metrics: dict[str, Any]
    artifacts: dict[str, str]
    notes: list[str]


class RegionOut(BaseModel):
    id: int
    ordinal: int
    x: int
    y: int
    w: int
    h: int
    area_fraction: float
    reference_text: str | None
    marketplace_text: str | None
    ocr_reliable: bool
    difference_type: str
    severity: str
    detail: str
    ref_crop_path: str | None
    mkt_crop_path: str | None
    signal: float


class ComparisonOut(BaseModel):
    id: int
    label: str | None
    reference_path: str
    marketplace_path: str
    reference_sha256: str | None
    marketplace_sha256: str | None
    verdict: str | None
    confidence: float
    status: str
    error: str | None
    duration_ms: float
    pipeline_version: str
    created_at: str
    region_count: int = 0
    worst_severity: str = "NONE"
    # Preview images, relative to the static `data/` mount.
    reference_image: str | None = None
    marketplace_image: str | None = None


class ComparisonDetailOut(ComparisonOut):
    config: dict[str, Any]
    stages: list[StageOut]
    regions: list[RegionOut]


class Page(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[ComparisonOut]


class CreatedOut(BaseModel):
    id: int
    status: str


class BatchCreatedOut(BaseModel):
    created: list[CreatedOut]
    unmatched: list[str]


class ConfigOut(BaseModel):
    values: dict[str, Any]
    editable: list[str]
    calibrated: bool
    calibration: dict[str, Any] | None = None
    ocr_backends: list[str]
    ocr_active: str


class ConfigUpdate(BaseModel):
    values: dict[str, Any]
