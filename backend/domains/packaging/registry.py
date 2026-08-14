"""Artwork registry -> engine candidate sets.

The adapter boundary. Everything the engine needs about a product's approved
artwork is packed into `CandidateSet` here; everything the engine does not need —
labels, approval dates, field metadata — rides along in `meta` and comes back out
on the other side.

These objects replace the hand-marshalled dicts the old pipeline built to get data
into worker processes. They are frozen dataclasses, so they pickle for the process
pool without a bespoke conversion step.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from core.types import Candidate, CandidateSet, Discriminator
from db.models import ArtworkVersion, DiscriminatingRegion, Product


def candidate_from_version(version: ArtworkVersion) -> Candidate:
    return Candidate(
        id=str(version.id),
        content_hash=version.sha256,
        image_path=Path(version.file_path),
        # The row id is the stable tie-break rank. Ranking has to be reproducible
        # when two candidates score identically, and ordering on the string id
        # would put "10" before "9".
        order=version.id,
        meta={
            "label": version.version_label,
            "is_current": bool(version.is_current),
            "width": version.width,
            "height": version.height,
            "approved_at": version.approved_at,
            "product_id": version.product_id,
        },
    )


def discriminator_from_region(region: DiscriminatingRegion) -> Discriminator:
    return Discriminator(
        from_id=str(region.from_version_id),
        to_id=str(region.to_version_id),
        box=(region.x, region.y, region.w, region.h),
        meta={
            "field_key": region.field_key,
            "old_value": region.old_value,
            "new_value": region.new_value,
            "severity": region.severity,
            "edit_type": region.edit_type,
            "area_fraction": region.area_fraction,
        },
    )


def build_candidate_sets(db) -> dict[str, CandidateSet]:
    """One candidate set per product that has at least one registered version."""
    sets: dict[str, CandidateSet] = {}
    for product in db.scalars(select(Product).order_by(Product.id)):
        versions = db.scalars(
            select(ArtworkVersion)
            .where(ArtworkVersion.product_id == product.id)
            .order_by(ArtworkVersion.id)
        ).all()
        if not versions:
            continue
        regions = db.scalars(
            select(DiscriminatingRegion)
            .where(DiscriminatingRegion.product_id == product.id)
            .order_by(DiscriminatingRegion.id)
        ).all()
        sets[product.id] = CandidateSet(
            key=product.id,
            candidates=tuple(candidate_from_version(v) for v in versions),
            discriminators=tuple(discriminator_from_region(r) for r in regions),
        )
    return sets


def current_candidate(cset: CandidateSet) -> Candidate:
    """The approved version — the one every listing is supposed to be serving.

    Falls back to the highest-ordered candidate if no row is flagged current, which
    keeps a registry with a missing flag usable rather than crashing a run.
    """
    for c in cset.candidates:
        if c.meta.get("is_current"):
            return c
    return max(cset.candidates, key=lambda c: c.order)


def resolve_within_group(cset: CandidateSet, matched: Candidate,
                         current: Candidate) -> Candidate:
    """Pick which label of a byte-identical group to report.

    Prefer the approved one: a listing serving bytes identical to the approved
    artwork is compliant, and reporting it under an older label would be a false
    alarm — the failure mode that gets a compliance tool switched off.
    """
    group = cset.hash_groups().get(matched.content_hash, (matched,))
    for c in group:
        if c.id == current.id:
            return current
    return group[0]
