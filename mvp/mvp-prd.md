# Pairwise Packaging Comparison — MVP Build Spec

A proof-of-concept that reduces the existing version-identification system to a single
question, answered one pair at a time, with every intermediate step made visible.

This document assumes the existing codebase described in `TECHNICAL.md`. Read §1 before
touching anything — the change in question being asked has consequences that are not
obvious from the diff.

---

## 1. CRITICAL: what question this system answers now

The existing build answers:

> Which of our N known artwork versions is this listing serving a copy of?

This build answers:

> Given **one** reference image and **one** marketplace image, are they the same
> artwork — and if not, exactly what differs, in words?

These are not the same problem, and the second is harder.

### What is lost, and why that is expected

The existing system's accuracy comes from two mechanisms that **cannot exist here**:

1. **Discriminating regions** are derived by diffing consecutive artwork versions. With
   one reference there is no second version to diff against, so there are no
   pre-computed boxes telling the pipeline where to look. It must find changed regions
   from scratch, on a noisy image.

2. **Relative candidate ranking** works because every candidate suffers the same JPEG
   damage, so the damage cancels as a common term. With one candidate there is nothing
   to rank against. Every judgement becomes absolute, measured against a threshold.

The consequence, stated plainly so it is not mistaken for a regression: **on pairs that
differ by a single number, pixel-level detection will be materially less reliable than
the 99.2% the version-identification build achieves.** The signal is genuinely below the
compression noise floor and there is no longer a trick available to lift it out.

### What replaces them

**OCR.** If the change cannot be reliably separated from noise geometrically, separate it
semantically. The pixel stage becomes a *generous candidate proposer* — deliberately
tuned for recall, accepting false positives — and the OCR stage becomes the *decider*.

A 300-pixel delta at 0.013% of frame is ambiguous. `"450mg"` versus `"480mg"` is not.

This inverts the tuning philosophy of the existing build at the pixel stage only. The
refuse-rather-than-guess principle still governs the **final** verdict.

### Why this is the right thing to build now

The version-identification method depends on a premise that has not yet been verified
against real data: that marketplace images are re-encoded copies of the brand's own
file. This build makes no such assumption. It uses registration-based comparison, which
works whether the marketplace image is a re-encoded copy **or** a third-party
photograph. It is slower and less accurate on the easy case, and it is the only thing
that works if the easy case turns out not to hold.

Treat this as an instrument for characterising real data, not as a downgrade of the
production pipeline.

---

## 2. Scope

**In:**
- Upload a reference image and a marketplace image as a pair
- Run the full comparison offline, one pair at a time
- Expose **every intermediate stage** with its own artefacts and confidence
- OCR-backed region-level text comparison
- Frontend inspection tool that makes the method legible to a non-engineer
- Pairwise test corpus + accuracy harness

**Out:**
- Version registries, version chains, discriminating regions, delta walking
- Batch runs, review queues, acknowledgements, dashboards, run history
- Scraping
- Any claim about production throughput

---

## 3. What to keep, cut, and build

### Keep unchanged

```
core/imaging/loader.py      decode, ICC, alpha flatten, hashing
core/imaging/geometry.py    de-pad, sub-pixel edges, resample, align
core/imaging/metrics.py     difference scores, region signal
core/imaging/regions.py     connected components, box relations
core/types.py               Probe, StageOutcome, MatchResult
core/engine.py              stage runner, evidence collection, refuse-by-default
core/config.py              typed EngineConfig
core/harness.py             labelled-case evaluation
core/logging.py
tools/calibrate.py          noise floor still governs the pixel threshold
frontend/src/lib/meaning.ts colour-as-signal discipline — extend, don't replace
```

### Delete

```
core/stages/discriminating_region.py    requires >= 2 versions
core/stages/single_candidate.py         candidate-set concept is gone
core/stages/whole_image.py              screening across candidates is gone
domains/packaging/registry.py
domains/packaging/deltas.py             version chain walking
runner/                                 entire batch layer
db/models.py                            Run, Finding, Acknowledgement,
                                        ArtworkVersion, DiscriminatingRegion
frontend/src/pages/                     Dashboard, ReviewQueue, Runs, RunProgress
```

### Build new

```
core/stages/registration.py     SIFT/AKAZE -> RANSAC homography -> warp
core/stages/structural_diff.py  SSIM over local windows -> regions
core/stages/region_ocr.py       OCR both sides of each region
core/stages/text_compare.py     type-aware text diff -> severity
core/trace.py                   stage-by-stage artefact + evidence recorder
domains/packaging/compare.py    one pair, end to end
db/models.py                    Comparison, ComparisonStage, ComparisonRegion
frontend/src/pages/             Compare, ComparisonDetail, History, Settings
frontend/src/components/StageInspector.tsx   the signature component
```

`core/engine.py` keeps its stage protocol and registry. This is a different stage set,
not a different engine.

---

## 4. CRITICAL: the trace layer

Every stage must emit inspectable artefacts. This is not debug instrumentation bolted on
afterwards — **it is the product**. The frontend exists to display it.

```python
@dataclass
class StageTrace:
    stage: str                   # "registration"
    status: str                  # OK | DEGRADED | FAILED | SKIPPED
    duration_ms: float
    confidence: float | None     # 0..1, stage-specific meaning
    metrics: dict                # numeric evidence, e.g. {"inliers": 214}
    artifacts: dict[str, str]    # name -> relative image path
    notes: list[str]             # plain-language explanation for the UI
```

Persist every trace. Write artefacts to `data/comparisons/{id}/{stage}/{name}.png`.

`notes` must be written for a **non-engineer reading the screen**. Not
`"inliers=214, cond=8.3"` but `"Found 214 matching points between the two images. The
alignment is well-conditioned."` The numbers belong in `metrics` and get rendered
separately.

A stage that fails must still emit a trace explaining what it saw and why it stopped.
Silent failure is the one unacceptable outcome, because the entire purpose of this build
is to show the method working or not working.

---

## 5. The pipeline

### Stage 0 — Load and normalize

Reuse `core/imaging/loader.py` and `geometry.py` unchanged: decode, ICC to sRGB, flatten
alpha onto white, de-pad.

Do **not** resize to a common size here. Registration handles scale. Forcing a resize
before registration destroys information the homography needs.

Artefacts: `reference_normalized.png`, `marketplace_normalized.png`, plus a padding
overlay showing what was cropped.

### Stage 1 — Hash

SHA-256 both files. If identical, emit `IDENTICAL` with confidence 1.0 and skip the rest.
Keep this even though it will rarely fire — when it does, it is proof, and the UI should
say so.

### Stage 2 — Registration

Per the TODO already written in `pipeline/fallback.py`:

1. SIFT keypoints on both (grayscale). Fall back to AKAZE if SIFT yields under 100
   keypoints on either side.
2. FLANN or BF matching, Lowe ratio test at 0.75.
3. RANSAC to a homography, reprojection threshold 3.0px.
4. **Reject on poor quality**, not just on failure to converge:
   - inliers < 30 → `DEGRADED`
   - inliers < 15 → `FAILED`, stop the pipeline here
   - homography condition number > 1e6 → `FAILED` (degenerate transform)
   - implied scale outside [0.25, 4.0] → `FAILED` (nonsense match)
5. Warp the reference into the marketplace frame. Mask to the valid overlap region.

Confidence must reflect **homography quality**, not just inlier count: combine
normalised inlier count, mean reprojection error, and overlap fraction.

Artefacts: keypoint match visualisation (draw the inlier correspondences), the warped
reference, the overlap mask, a checkerboard blend of warped-reference and marketplace
so alignment quality is visible at a glance.

Metrics: `keypoints_ref`, `keypoints_mkt`, `matches_raw`, `matches_after_ratio`,
`inliers`, `inlier_ratio`, `mean_reprojection_error`, `condition_number`,
`implied_scale`, `implied_rotation_deg`, `overlap_fraction`.

The checkerboard blend is the single most persuasive artefact in the whole system. Give
it prominence.

### Stage 3 — Structural diff

**SSIM over local windows, not absolute pixel difference.** Registration is never
pixel-exact, and illumination and white balance differences make raw subtraction useless
on a photographed pack. This is the documented reason the fallback track exists.

1. Convert both to grayscale; also retain a chroma channel comparison — a pure palette
   change moves chroma while barely moving luma. (This is the bug already found and
   fixed once in the existing build; do not reintroduce it.)
2. `skimage.metrics.structural_similarity(..., full=True)` → per-pixel SSIM map.
3. Invert to a difference map, threshold.
4. Morphological open (3×3) then close (7×7) — kill speckle, merge characters into
   word-level blobs.
5. Connected components → boxes. Discard under 0.05% of overlap area.

**Tune this stage for recall, not precision.** Its output is candidate regions for OCR,
not findings. A false region costs one OCR call. A missed region is invisible forever.
Set the threshold at roughly the 95th percentile of the calibrated noise floor rather
than the 99.9th.

Artefacts: SSIM heatmap (perceptually sensible colourmap, not jet), thresholded binary
mask, post-morphology mask, boxes drawn on the marketplace image.

Metrics: `global_ssim`, `regions_before_filter`, `regions_after_filter`,
`changed_area_fraction`, `threshold_used`.

### Stage 4 — Region OCR

For each surviving region, crop from **both** images with 10% padding on each side (OCR
degrades badly on tight crops) and run OCR on each.

Use PaddleOCR. Upscale crops below 300px on the long edge by 2–3× before OCR — small-text
recognition improves substantially and cost is irrelevant at this volume.

Per region, store: `reference_text`, `marketplace_text`, per-token confidences, and both
crops as artefacts.

**Calibrate OCR against itself.** Run OCR twice on the reference crop at different
scales. If the two readings disagree, mark the region `ocr_unreliable`. Any text
difference found in an unreliable region routes to `UNCERTAIN`, never to a positive
finding. This is the one mechanism available for distinguishing OCR error from real
change without a second reference, so it is not optional.

### Stage 5 — Text comparison

Normalize before comparing: Unicode NFKC, collapse whitespace, case-fold, unify unit
variants (`g`/`gm`/`gram`, `kcal`/`Kcal`), unify number formats (`0.5`/`.5`/`0,5`).

Token-align the two strings (`difflib.SequenceMatcher`), then classify each difference
**by type, never by string equality**:

| Difference | Classification |
|---|---|
| Number changed, same unit — compared **numerically** | `MATERIAL` |
| Number changed, unit also changed | `MATERIAL` |
| Same value, different format | `COSMETIC` |
| Edit distance 1 with confusable chars (`0/O`, `1/l`, `5/S`, `rn/m`) | `UNCERTAIN` |
| Region flagged `ocr_unreliable` | `UNCERTAIN` |
| Punctuation or whitespace only | `COSMETIC` |
| Word added or removed | `MATERIAL` |
| Region has a visual change but no text on either side | `VISUAL_ONLY` |

`VISUAL_ONLY` matters — a removed certification mark is a real material change with no
text to compare. Do not discard these; surface them for human judgement.

Numbers are parsed and compared as numbers. `450` and `450.0` must not fire.

### Stage 6 — Verdict

| Condition | Verdict |
|---|---|
| Hashes identical | `IDENTICAL` |
| Registration failed | `CANNOT_COMPARE` |
| No regions survived filtering | `MATCH` |
| Only `COSMETIC` differences | `MATCH_WITH_COSMETIC_DIFFERENCES` |
| Any `MATERIAL` difference | `DIFFERENT` |
| Only `UNCERTAIN` / `VISUAL_ONLY` differences | `NEEDS_REVIEW` |

`CANNOT_COMPARE` and `NEEDS_REVIEW` are **designed outcomes, not failures**, and the UI
must present them that way. Carry over the existing build's discipline here: it is
better to decline than to guess.

---

## 6. Data model

```
Comparison
  id                  INTEGER PK
  reference_path      TEXT
  marketplace_path    TEXT
  reference_sha256    TEXT
  marketplace_sha256  TEXT
  label               TEXT NULL      -- user's own note, e.g. "SKU001 front"
  verdict             TEXT
  confidence          REAL
  pipeline_version    TEXT
  config_json         TEXT           -- frozen at run time
  duration_ms         REAL
  status              TEXT           -- QUEUED | RUNNING | COMPLETE | FAILED
  created_at          TEXT

ComparisonStage
  id                  INTEGER PK
  comparison_id       INTEGER FK
  stage               TEXT
  ordinal             INTEGER
  status              TEXT
  confidence          REAL NULL
  duration_ms         REAL
  metrics_json        TEXT
  artifacts_json      TEXT
  notes_json          TEXT

ComparisonRegion
  id                  INTEGER PK
  comparison_id       INTEGER FK
  x, y, w, h          INTEGER        -- marketplace frame
  area_fraction       REAL
  reference_text      TEXT NULL
  marketplace_text    TEXT NULL
  ocr_reliable        BOOLEAN
  difference_type     TEXT
  severity            TEXT
  ref_crop_path       TEXT
  mkt_crop_path       TEXT
```

SQLite. No migrations tooling needed at this scale — but keep the SQLAlchemy 2.x layer
so the existing patterns carry over.

---

## 7. API

Small and pair-shaped. No run orchestration.

```
POST   /api/comparisons              multipart: reference, marketplace, label?
                                     -> 202 {id}
GET    /api/comparisons              list, paged, filter by verdict
GET    /api/comparisons/{id}         full detail: verdict, stages, regions
GET    /api/comparisons/{id}/stages  ordered traces with metrics and artefacts
GET    /api/comparisons/{id}/stream  SSE: stage-by-stage progress as it runs
DELETE /api/comparisons/{id}

POST   /api/comparisons/batch        multipart: multiple pairs by filename convention
                                     ref__<name>.png / mkt__<name>.png

GET    /api/config                   thresholds + calibration metadata
PUT    /api/config                   whitelisted keys, marks calibrated:false

GET    /api/artifacts/{path}         static image serving
GET    /api/health
```

Run comparisons on a worker thread, report progress through the database, stream via
SSE. Reuse the pattern already working in `POST /api/runs`.

Serve artefacts from a static mount. Never base64 into JSON.

---

## 8. Frontend

React 18 + Vite + TypeScript + Tailwind + TanStack Query + React Router. Recharts only
if a metric genuinely needs a chart.

### Screens

**Compare** (landing) — Two drop zones, side by side: *Reference artwork* and
*Marketplace image*. Drag-and-drop or click. Thumbnail previews on drop, with dimensions
and file size shown. Optional label field. A single "Compare" action.

Below: a batch mode accepting a folder of files following the `ref__` / `mkt__` naming
convention, listing detected pairs before running.

Empty state must say what to do, not apologise for being empty.

**ComparisonDetail** — The main screen. See §8.1.

**History** — Table of past comparisons: thumbnails, label, verdict, confidence,
duration. Filter by verdict. Click through to detail. This is a log, not a work queue —
keep it plain.

**Settings** — Threshold values with the calibration chart beside them, so numbers have
context. Editing marks the config as no longer purely measured.

### 8.1 ComparisonDetail — the signature screen

The verdict sits at the top, stated in plain language with its confidence and a one-line
explanation of what it means.

Below it, a **StageInspector**: a vertical sequence of every pipeline stage, each showing
status, duration, confidence, and expandable to reveal its artefacts, metrics table, and
plain-language notes.

Stage-specific views:

| Stage | Primary view |
|---|---|
| Load & normalize | Before/after with the removed padding highlighted |
| Hash | Both hashes, monospace, with equal/unequal stated outright |
| Registration | **Checkerboard blend** as the hero; keypoint match lines as a toggle; metrics table |
| Structural diff | SSIM heatmap with an opacity slider over the marketplace image; toggle raw mask vs post-morphology vs final boxes |
| Region OCR | Per region: both crops side by side, magnified, with OCR text beneath each |
| Text comparison | Per region: word-level diff with additions and deletions marked |

Region list beside the inspector. Clicking a region scrolls to it and highlights the
corresponding box in every stage view that draws boxes.

**Make it steppable.** A "play" control that advances through stages one at a time, with
the image view updating. Someone watching over your shoulder should understand the method
without you narrating it. That is the entire point of this build.

### 8.2 Design direction

Extend `lib/meaning.ts` — do not replace it. Add verdict and difference-type styles
there and nowhere else. Colour continues to carry meaning only: verdict, severity, and
diff add/remove. Everything else stays neutral.

This screen is an instrument, not a dashboard. Bias toward: a monospace face for all
numbers, hashes and metrics; generous space around images because the images *are* the
content; no cards-with-shadows; no gradient accents.

Avoid the current default AI-app looks: cream-with-serif-and-terracotta, near-black with
one acid accent, and soft-shadow card grids.

Quality floor, unannounced: keyboard navigation between stages, visible focus rings,
`prefers-reduced-motion` respected, and image viewers that support zoom and pan with
synchronised state across panes.

Copy: active voice, sentence case, consistent verbs. Name what the user controls.
`CANNOT_COMPARE` renders as "Couldn't align these images" with the hint *"Not enough
matching detail was found to line the two images up. This usually means they show
different products, or one is too low-resolution."*

---

## 9. Test corpus

Adapt `tools/corpus.py` to emit **pairs** rather than version chains.

```
python -m tools.corpus pairs --out ./data/pairs --count 200
```

Each case is `(reference, marketplace, expected_verdict, expected_regions)`:

| Case class | Construction | Expected |
|---|---|---|
| `IDENTICAL` | byte copy | `IDENTICAL` |
| `REENCODED` | JPEG q95/85/75/60, resized, padded | `MATCH` |
| `NUMERIC_DRIFT` | one nutrition value edited, then re-encoded | `DIFFERENT`, region located, old→new read correctly |
| `CLAIM_REMOVED` | badge deleted | `DIFFERENT` |
| `CERT_REMOVED` | mark deleted, no text | `DIFFERENT` via `VISUAL_ONLY` |
| `PALETTE_SHIFT` | hue rotation | `MATCH_WITH_COSMETIC_DIFFERENCES` |
| `PHOTOGRAPHED` | perspective warp + lighting gradient + blur + glare | `MATCH` or `DIFFERENT` per underlying edit |
| `WRONG_PRODUCT` | different product entirely | `DIFFERENT` or `CANNOT_COMPARE` |
| `UNRELATED` | random noise | `CANNOT_COMPARE` |

The `PHOTOGRAPHED` class is the one that matters most — it is the case the existing
build cannot handle and this build exists to prove out. Apply a known homography so the
recovered matrix can be compared against ground truth directly.

Supplement with **20–30 real phone photographs** of any packaged product. Synthetic warps
do not reproduce real specular highlights on foil, real camera noise, or the particular
ways people frame product photos badly.

---

## 10. Acceptance criteria

```
test_identical_detected                byte copies -> IDENTICAL, confidence 1.0

test_reencoded_not_flagged             re-encoded unchanged artwork -> MATCH
                                       at q>=75. ZERO false DIFFERENT verdicts.
                                       Most important test in the suite.

test_numeric_drift_found_and_read      NUMERIC_DRIFT cases: region located AND
                                       old/new values read correctly by OCR.
                                       Report the two rates separately —
                                       localisation and reading fail differently.

test_registration_recovers_homography  PHOTOGRAPHED cases: recovered matrix within
                                       tolerance of the applied one.

test_registration_refuses_on_unrelated UNRELATED and WRONG_PRODUCT ->
                                       CANNOT_COMPARE, never a confident verdict.

test_cosmetic_not_material             PALETTE_SHIFT -> COSMETIC.

test_visual_only_surfaced              CERT_REMOVED reported despite no text.

test_determinism                       Same pair twice -> identical output
                                       excluding ids, timestamps, durations.

test_every_stage_emits_trace           Including failure paths. No stage may
                                       complete without a trace row.
```

---

## 11. Deliverables

1. Working pair comparison end to end over the synthetic corpus
2. `tools/corpus.py pairs` generating the corpus with ground truth
3. All acceptance tests passing
4. Frontend covering §8, with the StageInspector fully functional
5. `README.md`: setup, three commands to run the demo
6. `RESULTS.md` reporting, honestly and separately:
   - Verdict accuracy per case class and per JPEG quality
   - **Region localisation rate** vs **OCR read-correctness rate** — these are
     different failure modes and averaging them hides which one is the problem
   - Registration success rate on `PHOTOGRAPHED` and on the real photographs
   - Timing per stage
   - An explicit comparison against the version-identification build's numbers, with
     the explanation from §1 for why they differ

Item 6's final bullet is not optional. Someone will read the accuracy number, compare it
to 99.2%, and conclude the build regressed. The document must pre-empt that by stating
which question each number answers.

---

## 12. What this MVP is for

It exists to answer three questions about real data that cannot currently be answered:

1. **Are marketplace images re-encoded copies of the brand's file, or photographs?**
   This determines whether the fast version-identification track is viable at all.
2. **Can OCR reliably read the fields that matter off real packaging?** Benchmarks are
   run on documents; packaging has decorative type, low contrast, and curved surfaces.
3. **Does registration succeed on real listing images?** Everything downstream is noise
   if it does not.

Build the instrument, run it on real pairs as soon as any exist, and let the measurements
decide the architecture of the production system. Do not optimise this build for speed —
speed is what the other build is for.