"""Shared API helpers: session handling, URL mapping, acknowledgement resolution."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from db.models import Acknowledgement, ArtworkVersion, Finding
from db.session import SessionLocal
from pipeline.config import REPO_ROOT

DATA_ROOT = (REPO_ROOT / "data").resolve()
CALIBRATION_ROOT = (REPO_ROOT / "calibration").resolve()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def to_url(path: str | Path | None) -> str | None:
    """Map an absolute file path to a static URL.

    Images are served from a static mount rather than base64-encoded into JSON —
    the review queue would otherwise ship megabytes of duplicated pixels per page
    and lose HTTP caching entirely.
    """
    if not path:
        return None
    p = Path(path)
    try:
        return "/files/" + p.resolve().relative_to(DATA_ROOT).as_posix()
    except ValueError:
        pass
    try:
        return "/calibration/" + p.resolve().relative_to(CALIBRATION_ROOT).as_posix()
    except ValueError:
        return None


def ack_map(db, product_ids: list[str], reference_version_ids: list[int]) -> dict:
    """Acknowledgements keyed by (product_id, signature, reference_version_id).

    Acknowledgements are resolved when a finding is read, not stamped onto it when
    it is written. A reviewer signing off today must silence a finding that was
    written last week, and approving new artwork must resurface findings that were
    signed off against the old reference — neither works if the flag is frozen into
    the row at write time.
    """
    if not product_ids:
        return {}
    rows = db.scalars(
        select(Acknowledgement)
        .where(Acknowledgement.product_id.in_(set(product_ids)))
        .where(Acknowledgement.reference_version_id.in_(set(
            [v for v in reference_version_ids if v is not None])))
    ).all()
    return {(a.product_id, a.region_signature, a.reference_version_id): a for a in rows}


def decorate_regions(finding: Finding, acks: dict) -> tuple[list[dict], bool]:
    """Attach acknowledgement state to a finding's regions."""
    try:
        regions = json.loads(finding.regions_json or "[]")
    except json.JSONDecodeError:
        regions = []

    for r in regions:
        key = (finding.product_id, r.get("region_signature"), finding.current_version_id)
        a = acks.get(key)
        r["acknowledged"] = bool(a and a.decision == "ACKNOWLEDGED")
        r["note"] = a.note if a else None

    acknowledged = bool(regions) and all(r["acknowledged"] for r in regions)
    return regions, acknowledged


def version_labels(db) -> dict[int, str]:
    rows = db.execute(select(ArtworkVersion.id, ArtworkVersion.version_label)).all()
    return {vid: label for vid, label in rows}
