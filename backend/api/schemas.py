"""Response models for the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class VersionOut(BaseModel):
    id: int
    product_id: str
    version_label: str
    sha256: str
    width: int
    height: int
    is_current: bool
    approved_at: str
    image_url: str | None = None
    thumb_url: str | None = None


class ProductOut(BaseModel):
    id: str
    name: str
    brand: str
    version_count: int
    current_version: VersionOut | None = None
    last_verdict: str | None = None
    last_severity: str | None = None
    open_findings: int = 0


class RegionOut(BaseModel):
    x: int
    y: int
    w: int
    h: int
    scraped_box: list[int] | None = None
    field_key: str | None = None
    old: str | None = None
    new: str | None = None
    severity: str
    edit_type: str | None = None
    from_version: str | None = None
    to_version: str | None = None
    region_signature: str | None = None
    acknowledged: bool = False
    note: str | None = None


class FindingOut(BaseModel):
    id: int
    run_id: int
    product_id: str
    product_name: str | None = None
    verdict: str
    severity: str
    match_method: str
    confidence: float
    matched_version: str | None = None
    current_version: str | None = None
    matched_version_id: int | None = None
    current_version_id: int | None = None
    region_count: int
    acknowledged: bool
    created_at: str
    thumb_url: str | None = None
    source_name: str | None = None


class FindingDetail(FindingOut):
    regions: list[RegionOut] = []
    source_path: str
    width: int
    height: int
    error: str | None = None
    version_chain: list[str] = []


class FindingImages(BaseModel):
    scraped_url: str | None = None
    matched_url: str | None = None
    current_url: str | None = None
    diff_overlay_url: str | None = None
    scraped_size: list[int] | None = None
    matched_size: list[int] | None = None


class RunOut(BaseModel):
    id: int
    started_at: str
    finished_at: str | None
    status: str
    pipeline_version: str
    input_dir: str
    images_total: int
    images_processed: int
    images_cached: int
    error: str | None = None
    counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}


class RunCreate(BaseModel):
    input_dir: str


class AcknowledgeIn(BaseModel):
    decision: str = "ACKNOWLEDGED"
    note: str = ""
    created_by: str = "reviewer"


class Page(BaseModel):
    items: list[Any]
    total: int
    offset: int
    limit: int


class ThresholdsOut(BaseModel):
    values: dict[str, Any]
    calibration: dict[str, Any] | None = None
    chart_url: str | None = None
