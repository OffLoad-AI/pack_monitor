"""Stage 5 — text comparison.

Thin: `core/textnorm.py` does the work, this writes down what it said. The one
piece of judgement that lives here rather than there is the `ocr_unreliable`
override, because reliability is a property of how the region was *read*, not of
the two strings.

Two outcomes are easy to get wrong and are handled explicitly.

**`VISUAL_ONLY`** — a region with a real visual change and no text on either side.
A removed certification mark is exactly this: a material change with nothing to
read. Discarding those would quietly make the system blind to every non-text edit,
so they are surfaced for human judgement instead.

**`UNCERTAIN` from an unreliable reading** — where the reader could not read the
same crop the same way twice, a text difference is not evidence of a text change.
It becomes a request for review, never a finding.
"""

from __future__ import annotations

import difflib

from ..textnorm import compare_text, normalize
from ..trace import OK, StageTrace
from ..types import (
    COSMETIC,
    KIND_PALETTE,
    MATERIAL,
    NO_DIFFERENCE,
    NONE,
    OCR_UNRELIABLE,
    PALETTE_SHIFT,
    PairContext,
    TEXT_ADDED,
    TEXT_REMOVED,
    UNCERTAIN,
    VISUAL_ONLY,
)
from .base import register


class TextCompareStage:
    name = "text_compare"

    def applicable(self, ctx: PairContext) -> bool:
        return bool(ctx.regions)

    def run(self, ctx: PairContext) -> StageTrace:
        t = StageTrace(stage=self.name, status=OK)
        cfg = ctx.config.text

        counts = {MATERIAL: 0, UNCERTAIN: 0, COSMETIC: 0, NONE: 0}
        details: list[dict] = []

        for i, region in enumerate(ctx.regions, start=1):
            ref = region.reference_text or ""
            mkt = region.marketplace_text or ""
            comparison = compare_text(
                ref, mkt,
                numeric_relative_tolerance=cfg.numeric_relative_tolerance,
                confusable_max_distance=cfg.confusable_max_distance)

            has_text = bool(ref.strip() or mkt.strip())

            if region.kind == KIND_PALETTE:
                # Classified from pixel evidence, not from text: the previous
                # stage established that the change is colour spread across the
                # whole pack while the brightness structure — the printing — is
                # unchanged. That is a recolour, and a recolour does not change
                # what the pack claims.
                region.difference_type = PALETTE_SHIFT
                region.severity = COSMETIC
                region.detail = ("The whole pack has been recoloured. The wording and "
                                 "layout are unchanged, so nothing the pack claims has "
                                 "changed.")
            elif not has_text:
                # A visual change with nothing to read. Real, and not classifiable
                # any further without a person looking at it.
                region.difference_type = VISUAL_ONLY
                region.severity = UNCERTAIN
                region.detail = ("Something changed here, but there is no text on "
                                 "either side to compare — a mark, a logo or a "
                                 "graphic. A person has to judge this one.")
            elif comparison.difference_type == NO_DIFFERENCE:
                region.difference_type = NO_DIFFERENCE
                region.severity = NONE
                region.detail = ("The pixels differ here but the text reads the same "
                                 "on both sides, so this is print or compression "
                                 "difference, not a change to the wording.")
            elif region.ink_intact:
                # One side read text and the other read nothing, but the printing
                # is still there in the pixels. That is a failed read, and saying
                # so is better than either reporting a removal that did not
                # happen or asking for a review that has nothing to decide.
                region.difference_type = NO_DIFFERENCE
                region.severity = NONE
                region.detail = ("The reader picked up text on one side only, but the "
                                 "printing is still present on both. This is a reading "
                                 "failure, not a change to the pack.")
            elif not region.ocr_reliable:
                # An unreliable reading whose two sides are nearly the same
                # string is the reader wobbling on unchanged text, not a change
                # to the pack. Reporting those as "needs review" buries the real
                # ones: measured, it turned 14 of 29 unchanged re-encoded pairs
                # into review requests. A reading that is unreliable *and*
                # substantially different still goes to review, which is where
                # `450` against `480` lands when the crop is damaged.
                # ...unless what differs is a whole word appearing or vanishing.
                # The guard exists for a reader wobbling *within* tokens, which
                # is character-level noise; a clean word present on one side and
                # absent on the other is not that, however similar the two
                # strings look overall. Removing one word from a four-word
                # region leaves similarity around 0.79, so without this test the
                # guard swallows exactly the removals the tool exists to catch:
                # measured, "Vegan No palm oil" against "No palm oil" was
                # reported as MATCH. Such a region goes to review rather than to
                # a finding, because the reading is still unreliable.
                whole_word_gone = any(
                    d.difference_type in (TEXT_REMOVED, TEXT_ADDED)
                    for d in comparison.differences)
                similarity = _similarity(ref, mkt)
                if similarity >= cfg.unreliable_similarity and not whole_word_gone:
                    region.difference_type = NO_DIFFERENCE
                    region.severity = NONE
                    region.detail = (
                        f"Read as '{ref}' against '{mkt}'. The two readings are "
                        f"close enough that the difference is the reader wobbling "
                        f"on print and compression, not a change to the wording.")
                else:
                    region.difference_type = OCR_UNRELIABLE
                    region.severity = UNCERTAIN
                    region.detail = (f"The text appears to differ — read as '{ref}' "
                                     f"against '{mkt}' — but this region could not "
                                     f"be read consistently, so the difference may "
                                     f"be a misreading. Needs a person to confirm.")
            else:
                region.difference_type = comparison.difference_type
                region.severity = comparison.severity
                region.detail = comparison.detail

            counts[region.severity] = counts.get(region.severity, 0) + 1
            details.append({
                "region": i,
                "box": list(region.box),
                "reference_text": ref,
                "marketplace_text": mkt,
                "ocr_reliable": region.ocr_reliable,
                "difference_type": region.difference_type,
                "severity": region.severity,
                "opcodes": [[tag, a, b] for tag, a, b in comparison.opcodes],
            })

        t.metric(regions=len(ctx.regions),
                 material=counts[MATERIAL], uncertain=counts[UNCERTAIN],
                 cosmetic=counts[COSMETIC], no_difference=counts[NONE],
                 comparisons=details)

        real = counts[MATERIAL] + counts[UNCERTAIN] + counts[COSMETIC]
        t.confidence = (round(1.0 - counts[UNCERTAIN] / real, 4) if real else 1.0)

        t.note(f"Compared the text in {len(ctx.regions)} region(s), aligning word by "
               f"word and classifying each difference by what kind of difference it "
               f"is rather than by whether the strings match.")
        if counts[MATERIAL]:
            t.note(f"{counts[MATERIAL]} region(s) contain a change that alters what "
                   f"the pack says — a different value, unit or wording.")
        if counts[COSMETIC]:
            t.note(f"{counts[COSMETIC]} region(s) differ only in formatting: the same "
                   f"value written another way, or punctuation.")
        if counts[UNCERTAIN]:
            t.note(f"{counts[UNCERTAIN]} region(s) could not be settled automatically "
                   f"and are flagged for review rather than guessed at.")
        if counts[NONE]:
            t.note(f"{counts[NONE]} region(s) turned out to read identically and were "
                   f"discarded — expected, since the previous step is tuned to over-"
                   f"propose.")

        return t


def _similarity(a: str, b: str) -> float:
    """Character-level similarity of two readings, ignoring word boundaries.

    Whitespace is stripped first because where a recognizer puts a token break
    is an artefact of the recognizer. `450` against `480` scores 0.67 and stays
    reportable; `wholegrain` against `wholegraieain` scores 0.87 and does not.
    """
    x, y = normalize(a).replace(" ", ""), normalize(b).replace(" ", "")
    if not x and not y:
        return 1.0
    return difflib.SequenceMatcher(a=x, b=y, autojunk=False).ratio()


register("text_compare")(TextCompareStage)
