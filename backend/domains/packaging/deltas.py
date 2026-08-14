"""What changed between the version being served and the approved one.

A listing three versions behind should report everything that has changed since,
not just the last hop — so this walks the chain and collects every discriminating
region along the way.
"""

from __future__ import annotations

from core.types import Candidate, CandidateSet, Discriminator

from .verdict import region_signature


def path_discriminators(cset: CandidateSet, matched: Candidate,
                        current: Candidate) -> list[Discriminator]:
    """Every discriminating region on the chain from `matched` to `current`.

    Returns nothing when the matched version is not behind the approved one —
    there is no forward path, so there is nothing stale to report.
    """
    order = [c.id for c in cset.candidates]
    try:
        i, j = order.index(matched.id), order.index(current.id)
    except ValueError:
        return []
    if i >= j:
        return []
    on_path = set(zip(order[i:j], order[i + 1:j + 1]))
    return [d for d in cset.discriminators if (d.from_id, d.to_id) in on_path]


def map_to_probe_box(box: tuple[int, int, int, int],
                     crop_box: tuple[int, int, int, int],
                     ref_w: int, ref_h: int) -> list[int]:
    """Reference coordinates -> coordinates on the original listing file.

    The reviewer looks at the file as downloaded, padding and all, so a box in
    reference space has to be scaled by the content rectangle and shifted by where
    that rectangle sat. Otherwise the overlay lands somewhere they are not looking.
    """
    cx, cy, cw, ch = crop_box
    sx = cw / ref_w
    sy = ch / ref_h
    return [int(round(cx + box[0] * sx)), int(round(cy + box[1] * sy)),
            max(1, int(round(box[2] * sx))), max(1, int(round(box[3] * sy)))]


def build_deltas(cset: CandidateSet, matched: Candidate, current: Candidate,
                 normalized=None) -> list[dict]:
    """The reviewer-facing change list for one finding.

    Denormalized on purpose: these are written to the finding as JSON so the review
    queue can render a row without joining back to the region table.
    """
    if matched.id == current.id or matched.content_hash == current.content_hash:
        return []

    labels = {c.id: c.meta.get("label") for c in cset.candidates}
    product_id = cset.key
    out: list[dict] = []

    for d in path_discriminators(cset, matched, current):
        x, y, w, h = d.box
        entry = {
            "x": x, "y": y, "w": w, "h": h,
            "field_key": d.meta.get("field_key"),
            "old": d.meta.get("old_value"),
            "new": d.meta.get("new_value"),
            "severity": d.meta.get("severity", "UNKNOWN"),
            "edit_type": d.meta.get("edit_type"),
            "from_version": labels.get(d.from_id),
            "to_version": labels.get(d.to_id),
            "region_signature": region_signature(
                product_id, x, y, w, h, d.meta.get("field_key")),
        }
        if normalized is not None:
            entry["scraped_box"] = map_to_probe_box(
                d.box, normalized.crop_box,
                matched.meta["width"], matched.meta["height"])
        else:
            entry["scraped_box"] = list(d.box)
        out.append(entry)

    return out
