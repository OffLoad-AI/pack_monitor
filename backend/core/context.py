"""Per-probe working state, memoized.

Stages are cheap to reorder precisely because none of them owns an intermediate
result. The normalized probe, each prepared pair and each difference score live
here and are computed once, so the region stage reuses whatever the whole-image
stage already paid for instead of being handed it as a parameter.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Protocol

import numpy as np

from .config import EngineConfig
from .imaging import geometry as G
from .imaging import metrics as M
from .imaging.loader import load_rgb
from .types import Candidate, CandidateSet, Probe

# A decoded 1500x1500 reference is ~6.5MB. Caching every candidate a worker ever
# touches costs hundreds of megabytes per process and, at one worker per core,
# exhausts memory outright. Dispatching in candidate-set order keeps a worker on
# one set at a time, so a small cache still hits on essentially every lookup.
REFERENCE_CACHE_MAX = 8


class ImageStore(Protocol):
    """Where decoded candidate images come from. Injectable so tests need no disk."""

    def get(self, candidate: Candidate) -> np.ndarray: ...


class LruImageStore:
    """Bounded decoded-image cache, keyed by candidate id."""

    def __init__(self, max_items: int = REFERENCE_CACHE_MAX):
        self._max = max_items
        self._items: OrderedDict[str, np.ndarray] = OrderedDict()

    def get(self, candidate: Candidate) -> np.ndarray:
        img = self._items.get(candidate.id)
        if img is None:
            img = load_rgb(candidate.image_path)
            self._items[candidate.id] = img
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        else:
            self._items.move_to_end(candidate.id)
        return img


class DictImageStore:
    """In-memory store for tests and for reusing already-decoded arrays."""

    def __init__(self, images: dict[str, np.ndarray]):
        self._images = images

    def get(self, candidate: Candidate) -> np.ndarray:
        return self._images[candidate.id]


class MatchContext:
    """Everything one identification needs, computed on demand and kept."""

    def __init__(self, probe: Probe, candidates: CandidateSet,
                 config: EngineConfig, store: ImageStore | None = None):
        self.probe = probe
        self.candidates = candidates
        self.config = config
        self.store = store if store is not None else LruImageStore()

        self._normalized: G.NormalizedImage | None = None
        self._prepared: dict[str, tuple[np.ndarray, np.ndarray, float]] = {}
        self._scores: dict[str, np.ndarray] = {}
        self._fractions: dict[str, float] = {}

    # -- probe --------------------------------------------------------------

    @property
    def normalized(self) -> G.NormalizedImage:
        """Decoded, colour-corrected and de-padded probe.

        Resizing and alignment are deliberately not done here: the working size
        depends on which candidate is being compared against.
        """
        if self._normalized is None:
            n = self.config.normalize
            self._normalized = G.normalize_image(
                self.probe.path, n.border_uniform_tolerance,
                n.max_border_crop_fraction)
        return self._normalized

    # -- per candidate ------------------------------------------------------

    def reference(self, candidate: Candidate) -> np.ndarray:
        return self.store.get(candidate)

    def prepared(self, candidate: Candidate) -> tuple[np.ndarray, np.ndarray, float]:
        """(probe_work, candidate_work, scale) on a common grid, aligned."""
        cached = self._prepared.get(candidate.id)
        if cached is None:
            cached = G.prepare_pair(self.normalized.rgb, self.reference(candidate))
            self._prepared[candidate.id] = cached
        return cached

    def score(self, candidate: Candidate) -> np.ndarray:
        """Normalized difference map against one candidate; 1.0 is the threshold."""
        cached = self._scores.get(candidate.id)
        if cached is None:
            probe_work, cand_work, _scale = self.prepared(candidate)
            d = self.config.diff
            cached = M.diff_score(probe_work, cand_work, d.luma_threshold,
                                  d.chroma_threshold, d.tolerance_radius)
            self._scores[candidate.id] = cached
        return cached

    def whole_fraction(self, candidate: Candidate) -> float:
        """Share of pixels differing by more than compression noise."""
        cached = self._fractions.get(candidate.id)
        if cached is None:
            cached = M.changed_fraction(self.score(candidate), 1.0,
                                        self.config.morphology.open)
            self._fractions[candidate.id] = cached
        return cached

    def scale(self, candidate: Candidate) -> float:
        return self.prepared(candidate)[2]

    def working_shape(self, candidate: Candidate) -> tuple[int, int]:
        s = self.score(candidate)
        return s.shape[1], s.shape[0]

    # -- convenience --------------------------------------------------------

    def ranked_by_fraction(self,
                           subset: tuple[Candidate, ...] | None = None
                           ) -> list[tuple[Candidate, float]]:
        """Candidates cheapest-difference first, ties broken reproducibly."""
        pool = subset if subset is not None else self.candidates.representatives()
        scored = [(c, self.whole_fraction(c)) for c in pool]
        scored.sort(key=lambda cf: (cf[1], cf[0].order))
        return scored
