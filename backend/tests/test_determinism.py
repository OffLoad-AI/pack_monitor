"""Determinism (§11).

A monthly compliance report that flags different things on different runs over
unchanged inputs destroys trust immediately, so this is a hard requirement rather
than a quality target.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from db.models import Finding, ScrapedImage
from db.session import SessionLocal


def _fingerprint(run_id: int) -> list[tuple]:
    """Everything about a run's findings except identifiers and timestamps."""
    with SessionLocal() as db:
        rows = db.execute(
            select(Finding, ScrapedImage)
            .join(ScrapedImage, Finding.scraped_image_id == ScrapedImage.id)
            .where(Finding.run_id == run_id)).all()

    out = []
    for f, img in rows:
        regions = json.loads(f.regions_json or "[]")
        # diff_map_path embeds the run id, so compare only its filename.
        diff_name = f.diff_map_path.rsplit("/", 1)[-1] if f.diff_map_path else None
        out.append((
            img.source_path, img.sha256, f.product_id, f.verdict, f.severity,
            f.match_method, round(f.confidence, 9),
            f.matched_version_id, f.current_version_id, diff_name,
            tuple((r["x"], r["y"], r["w"], r["h"], r.get("field_key"),
                   r.get("old"), r.get("new"), r["severity"],
                   r.get("region_signature")) for r in regions),
        ))
    out.sort(key=lambda t: t[0])
    return out


def test_determinism(fresh_env):
    """Two runs over the same input produce identical findings."""
    first = fresh_env.run(workers=4, use_cache=False)
    second = fresh_env.run(workers=4, use_cache=False)
    assert first != second

    a = _fingerprint(first)
    b = _fingerprint(second)

    assert len(a) == len(b), f"run sizes differ: {len(a)} vs {len(b)}"
    mismatches = [(x, y) for x, y in zip(a, b) if x != y]
    assert not mismatches, (
        f"{len(mismatches)} findings differ between identical runs; "
        f"first: {mismatches[0][0][0]}")
    print(f"\n  {len(a)} findings byte-identical across two runs")


def test_determinism_is_independent_of_worker_count(fresh_env):
    """Results must not depend on how the work was divided between processes."""
    one = fresh_env.run(workers=1, use_cache=False)
    many = fresh_env.run(workers=4, use_cache=False)

    a = _fingerprint(one)
    b = _fingerprint(many)
    assert a == b, "findings depend on worker count"
