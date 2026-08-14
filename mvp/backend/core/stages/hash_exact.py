"""Stage 1 — hash.

SHA-256 of both files' **raw bytes**, never decoded pixels: decoding depends on
library versions, so a pixel hash would not be stable across environments, and
stability is the entire point of this stage.

If the two hashes match, the images are the same file and no comparison is
performed or needed. This will rarely fire on real marketplace data — a
marketplace almost always re-encodes — but when it does fire it is **proof**
rather than an estimate, and the UI says so outright.
"""

from __future__ import annotations

from ..imaging.loader import sha256_file
from ..trace import OK, StageTrace
from ..types import IDENTICAL, PairContext
from .base import register


class HashStage:
    name = "hash"

    def applicable(self, ctx: PairContext) -> bool:
        return True

    def run(self, ctx: PairContext) -> StageTrace:
        t = StageTrace(stage=self.name, status=OK)

        ref = sha256_file(ctx.reference_path)
        mkt = sha256_file(ctx.marketplace_path)
        ctx.reference_sha256 = ref
        ctx.marketplace_sha256 = mkt

        equal = ref == mkt
        t.metric(reference_sha256=ref, marketplace_sha256=mkt, equal=equal)
        t.confidence = 1.0 if equal else None

        if equal:
            t.note("The two files are byte-for-byte identical.")
            t.note("This is proof, not an estimate: the marketplace is serving your "
                   "file unmodified. Nothing further needs to be compared.")
            ctx.verdict = IDENTICAL
            ctx.confidence = 1.0
            ctx.halt(IDENTICAL, "The files are byte-for-byte identical, so no "
                                "comparison was needed.")
        else:
            t.note("The two files differ in their bytes, which is expected — "
                   "marketplaces re-save images. This says nothing yet about whether "
                   "the artwork differs.")

        return t


register("hash")(HashStage)
