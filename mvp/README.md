# Pairwise packaging comparison

A proof-of-concept that reduces the version-identification system to a single
question, answered one pair at a time, with every intermediate step made visible.

> Given **one** reference image and **one** marketplace image, are they the same
> artwork — and if not, exactly what differs, in words?

Companion documents: [TECHNICAL.md](TECHNICAL.md) for how the pipeline works step
by step, [USER-GUIDE.md](USER-GUIDE.md) for operation, [RESULTS.md](RESULTS.md) for
measured accuracy, [mvp-prd.md](mvp-prd.md) for the build specification, and
[../TECHNICAL.md](../TECHNICAL.md) for the version-identification build this is cut
down from.

---

## Three commands

From `mvp/`:

```bash
# 1. install
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
(cd frontend && npm install)

# 2. generate a corpus, measure the noise floor, and score the result
cd backend
../.venv/bin/python -m tools.corpus pairs --out ../data/pairs --count 120
../.venv/bin/python -m tools.calibrate --pairs ../data/pairs
../.venv/bin/python -m tools.accuracy --pairs ../data/pairs --out ../RESULTS.json

# 3. run it
../.venv/bin/uvicorn api.main:app --port 8000     # then, in another terminal:
(cd ../frontend && npm run dev)                    # http://localhost:5173
```

`rapidocr-onnxruntime` must be installed with `--no-deps` — it declares
`opencv-python`, which installs a second full copy of OpenCV alongside the
headless build. `requirements.txt` lists its real dependencies explicitly:

```bash
.venv/bin/pip install --no-deps rapidocr-onnxruntime
```

Run the tests with `../.venv/bin/python -m pytest` from `backend/`.

---

## What this build is, and is not

The version-identification build answers *"which of our N known artwork versions
is this listing serving a copy of?"* — a closed-set lookup across fifteen thousand
listings a month, at 99.2% accuracy. This build answers a different and harder
question about **one pair**, and it is important to understand why the second is
harder before reading any accuracy number.

The other build's accuracy comes from two mechanisms that **cannot exist here**:

1. **Discriminating regions** are derived by diffing consecutive artwork
   versions. With one reference there is no second version to diff against, so
   there are no pre-computed boxes telling the pipeline where to look. It has to
   find changed regions from scratch, on a noisy image.

2. **Relative candidate ranking** works because every candidate suffers the same
   JPEG damage, so the damage cancels as a common term. With one candidate there
   is nothing to rank against. Every judgement becomes absolute, measured against
   a threshold.

Stated plainly so it is not mistaken for a regression: **on pairs differing by a
single number, pixel-level detection is materially less reliable here than the
99.2% the other build achieves.** The signal is genuinely below the compression
noise floor and there is no longer a trick available to lift it out.

What replaces them is **OCR**. If the change cannot be separated from noise
geometrically, separate it semantically. The pixel stage becomes a generous
*proposer* — tuned for recall, accepting false positives — and OCR becomes the
*decider*. A 300-pixel delta at 0.013% of frame is ambiguous; `450mg` versus
`480mg` is not.

And what this build buys in exchange: it makes **no assumption that the
marketplace image came from your file at all**. Registration by keypoints and a
homography works whether the marketplace image is a re-encoded copy *or* a
third-party photograph. It is slower and less accurate on the easy case, and it
is the only thing that works if the easy case turns out not to hold.

**Treat this as an instrument for characterising real data, not as a downgrade of
the production pipeline.**

---

## The pipeline

Seven stages. Every one emits an inspectable trace, including on the failure
paths — that is not debug instrumentation bolted on afterwards, **it is the
product**, and the frontend exists to display it.

| Stage | What it does |
|---|---|
| **Load and normalize** | Decode, ICC to sRGB, flatten alpha onto white, de-pad. No resize — registration handles scale, and a resize first destroys information the homography needs. |
| **Hash** | SHA-256 of both files' raw bytes. Equal means proof, and the pipeline stops. |
| **Registration** | SIFT (ORB fallback) → Lowe ratio test → RANSAC homography → warp. **Rejects on quality, not just on convergence.** |
| **Structural diff** | SSIM over local windows plus a separate chroma comparison → morphology → regions. Tuned for recall. |
| **Region OCR** | Crop both sides, upscale small crops, read each — and read each **twice at different scales** to check the reader against itself. |
| **Text comparison** | Normalize, token-align, classify each difference **by type, never by string equality**. |
| **Verdict** | Reduce the region list to one of six answers, two of which are refusals. |

### Layout

```
mvp/
  backend/
    core/                     the general pair-comparison engine
      types.py                verdicts, severities, RegionFinding, PairContext
      config.py               typed EngineConfig, flat<->nested, frozen per comparison
      paths.py                filesystem layout, PIPELINE_VERSION
      trace.py                StageTrace + TraceRecorder — the product
      engine.py               stage runner; refuses by default
      textnorm.py             normalization + typed difference classification
      logging.py
      imaging/                loader, geometry, metrics, regions   (kept unchanged)
      stages/                 load_normalize, hash, registration, structural_diff,
                              region_ocr, text_compare, verdict
      ocr/                    pluggable backends: paddle, rapid, null
    domains/packaging/
      compare.py              one pair, end to end
    db/                       Comparison, ComparisonStage, ComparisonRegion
    api/                      routes, worker thread, SSE progress
    tools/
      artwork.py              the renderer, lifted unchanged from the other build
      corpus.py               `pairs` — nine case classes with exact ground truth
      calibrate.py            noise-floor measurement
      accuracy.py             ground-truth evaluation
    tests/                    the spec's acceptance criteria, plus unit tests
  frontend/src/
    pages/                    Compare, ComparisonDetail, History, Settings
    components/               StageInspector, ImageViewer, RegionReadings,
                              StructuralDiffView, WordDiff, primitives
    lib/meaning.ts            colour-as-signal, extended not replaced
  config/thresholds.json      written by tools.calibrate
  calibration/noise_floor.png written by tools.calibrate
  data/                       pairs/, comparisons/, uploads/, db.sqlite
```

### Kept from the version-identification build

`core/imaging/{loader,geometry,metrics,regions}.py` unchanged, `core/logging.py`
unchanged, the renderer half of `tools/corpus.py` unchanged (as
`tools/artwork.py`), and the shape of `core/config.py`, `core/engine.py` and
`frontend/src/lib/meaning.ts`.

`tools/artwork.py` is deliberately byte-identical to its origin. The two builds'
accuracy numbers are only comparable at all if the artwork they were measured on
is the same artwork.

### Deleted

Version registries, version chains, discriminating regions, delta walking, the
batch runner, review queues, acknowledgements, dashboards, run history, and every
page that displayed them. Those all belong to a question this build does not ask.

---

## Deviations from the specification

Six, each measured rather than assumed. Where the specification is wrong about
this pipeline it is because it was written against the other one's behaviour.

**1. `AKAZE` → `ORB` as the registration fallback.**
OpenCV 5's Python bindings do not ship AKAZE. ORB fills the same role: a fast
binary-descriptor detector that finds corners where SIFT's blob response starves.

**2. The per-pixel threshold is the 99.9th percentile of the noise floor, not the
95th.**
The spec asks for the 95th, tuned for recall. Taken literally on a 1500×1500
frame that fires on 112,000 pixels of pure noise per pair, which survives the
morphology and proposes dozens of junk regions. The recall the spec wants is
bought elsewhere instead — by a generous region-area floor and by letting OCR
discard what survives — rather than by a generous per-pixel threshold.

**3. `min_region_area_fraction` is the spec's 0.05%, not the other build's
0.005%.**
Noted because the other build's `TECHNICAL.md` §14 documents 0.05% as *wrong*.
Both are right for their own pipeline: there, regions are per-digit and the
reference-vs-reference diff is noise-free; here, regions are merged to line level
and the noise floor is far higher. At 0.005% the artwork's trim ticks propose a
dozen junk regions along every edge.

**4. The closing kernel is anisotropic — 31px wide, 7px tall.**
The diff proposes where pixels changed; OCR needs whole text lines. A square
kernel either leaves a changed word as three fragments — and a crop of a fragment
reads as nonsense, which becomes a false material finding — or bridges the table
row above it. Measured: unchanged artwork read as `"hoco"` against `"Choco"`.

**5. The reader's self-consistency check runs on *both* sides, not just the
reference.**
The spec calls for re-reading the reference crop. The marketplace image is the
degraded one, so checking only the reference checks the easy side. Measured: a
glare-damaged crop read `"coffee ee"` against `"Coffee"` and would have been
reported as a material change.

**6. `CERT_REMOVED` produces `NEEDS_REVIEW`, and the spec contradicts itself
here.**
Its corpus table expects `DIFFERENT` "via `VISUAL_ONLY`"; its verdict table says
a comparison whose only differences are `VISUAL_ONLY` produces `NEEDS_REVIEW`.
Both cannot hold. The verdict table governs, because a removed mark genuinely
cannot be confirmed without a person — there is no text to read and nothing to
rank against. The corpus accepts either verdict and what the class actually tests
is that a change with no text is *found and attributed*, rather than discarded.

Plus one addition the spec does not mention: **a global-recolour collapse**. A hue
rotation decomposes into one component per coloured element, which is technically
accurate and useless to review. When a change is large, spread across the frame,
many-component and chroma-dominated, it collapses to one region meaning "the
palette moved" — and structural regions are then taken from the luma channel
alone, so a recolour cannot mask a changed number.

---

## Real data

The synthetic corpus does not reproduce real specular highlights on foil, real
camera noise, or the particular ways people frame product photos badly. Supplement
it: put 20–30 phone photographs of any packaged product alongside the artwork they
were shot from, name them `ref__name.png` / `mkt__name.jpg`, and drop the folder
on the Compare screen's batch panel.

That is the measurement this build exists to make. Everything else is scaffolding
for it.
