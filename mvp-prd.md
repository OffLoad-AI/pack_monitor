# Packaging Compliance Monitor — MVP Build Spec

You are building an MVP of an automated packaging-compliance monitoring tool. Read this
entire document before writing code. Sections marked **CRITICAL** contain decisions that
are easy to get wrong and expensive to reverse.

---

## 1. What this system does

A brand uploads approved packaging artwork to marketplaces (Amazon, Flipkart, etc.).
Over time, listings drift: sellers keep serving an old artwork version after the pack has
been revised, so outdated nutrition values, withdrawn claims, or expired certification
marks stay live on the storefront.

This tool runs monthly. For each product it compares the images currently live on the
marketplace against a repository of approved artwork versions, and reports which listings
are serving stale artwork and exactly what is wrong with it.

**Scale:** ~3,000 products, ~15,000 images per run. Runs once a month.

---

## 2. CRITICAL: the core architectural principle

This is **not** an image similarity problem. Do not build embedding search, do not build
a "how similar are these images" score, do not reach for a vision-language model as the
primary comparison mechanism.

The reference artwork and the scraped marketplace image **originate from the same file**.
The marketplace serves a re-encoded, resized copy of the exact image the brand uploaded.

So the real question is not *"do these look similar?"* It is:

> **Which known version of our artwork is this listing currently serving?**

That is a **version identification** problem, and it has an exact answer. The pipeline is
built to find that exact answer cheaply, and only falls back to fuzzy methods when no
exact answer exists (e.g. a third-party seller photographed the pack themselves).

Consequences that follow from this, all of which the code must respect:

- A byte-identical hash match is **proof**, not evidence. Never second-guess it.
- Pixel-by-pixel comparison with a tolerance threshold is the primary diff method.
- The output is a **version identity plus a field-level delta**, not a similarity score.
- Determinism is a hard requirement. Same inputs must always produce same outputs.

---

## 3. CRITICAL: things that will seem like good ideas and are not

**Do not use perceptual hashing (pHash/dHash) to decide if an image changed.**
pHash downscales to 32×32 and keeps only low-frequency DCT coefficients. At that
resolution a nutrition panel is a grey smudge. Changing sodium from 450mg to 480mg moves
the pHash by approximately zero bits. It would silently skip exactly the drift this tool
exists to detect. Use SHA-256 for exact matching and thresholded pixel diff for
near-matching.

**Do not send whole images to a VLM and ask "what changed".**
The images are 99.9% identical. Models are unreliable at spotting one changed digit
across near-identical pairs, and — worse — they are non-deterministic. A monthly
compliance report that flags different things on different runs with unchanged inputs
destroys user trust immediately.

**Do not use raw pixel equality.** JPEG re-encoding perturbs every pixel. The threshold
must be derived empirically (see §7.3), not set to zero and not guessed.

**Do not compute similarity over the whole image to distinguish versions.**
Two artwork versions differing only in one number are globally ~99.9% identical — below
the noise floor of JPEG compression. Version discrimination must happen inside the
specific regions known to differ (see §6.3).

---

## 4. MVP scope

**In scope:**
- Synthetic test corpus generator (build this FIRST — see §5)
- Offline reference processing: version registry, discriminating-region extraction
- Run pipeline: hash → normalize → pixel diff → region check → verdict
- SQLite persistence with full run history
- FastAPI backend
- React frontend with review queue and image comparison viewer
- Acknowledgement persistence (reviewed findings do not resurface)
- Threshold calibration tooling

**Out of scope for MVP (stub the interfaces, do not implement):**
- Web scraping — the run pipeline reads from a local directory instead
- OCR / field extraction — schema exists, populated by the corpus generator
- The photograph fallback track (SIFT/homography/SSIM) — leave a `TODO` module with
  the interface defined and a stub that returns `UNKNOWN_IMAGE`
- Authentication, multi-tenancy, email alerts

---

## 5. Build order

Build in this order. Each milestone must work before starting the next.

| # | Milestone | Done when |
|---|---|---|
| 1 | Synthetic corpus generator | Produces artwork versions + marketplace-transformed variants with a ground-truth JSON |
| 2 | Threshold calibration script | Outputs a noise-floor histogram and a recommended threshold |
| 3 | Offline reference processing | Version registry + discriminating regions in DB |
| 4 | Run pipeline | Correctly identifies version for every corpus image |
| 5 | API | All endpoints in §9 return real data |
| 6 | Frontend | All features in §10 |
| 7 | Acceptance tests | All tests in §11 pass |

Milestone 1 comes first because there is **no access to real artwork or real marketplace
data**. Everything is validated against synthetic data with known ground truth. This is
an advantage, not a compromise — the ground truth is exact.

---

## 6. Data model

SQLite via SQLAlchemy. All timestamps UTC ISO-8601.

```
Product
  id                TEXT PK          -- SKU
  name              TEXT
  brand             TEXT
  created_at        TEXT

ArtworkVersion
  id                INTEGER PK
  product_id        TEXT FK -> Product.id
  version_label     TEXT             -- "v1", "v2.1"
  file_path         TEXT
  sha256            TEXT INDEXED
  width             INTEGER
  height            INTEGER
  is_current        BOOLEAN          -- exactly one true per product
  approved_at       TEXT
  created_at        TEXT

DiscriminatingRegion
  id                INTEGER PK
  product_id        TEXT FK
  from_version_id   INTEGER FK -> ArtworkVersion.id
  to_version_id     INTEGER FK -> ArtworkVersion.id
  x, y, w, h        INTEGER          -- in from_version pixel coordinates
  area_fraction     REAL             -- region area / image area
  field_key         TEXT NULL        -- e.g. "sodium_mg", if mapped
  old_value         TEXT NULL
  new_value         TEXT NULL
  severity          TEXT             -- MATERIAL | COSMETIC | UNKNOWN

Run
  id                INTEGER PK
  started_at        TEXT
  finished_at       TEXT NULL
  status            TEXT             -- RUNNING | COMPLETE | FAILED
  pipeline_version  TEXT
  images_total      INTEGER
  images_processed  INTEGER
  images_cached     INTEGER          -- skipped via hash/near-match
  config_json       TEXT             -- thresholds used, frozen at run start

ScrapedImage
  id                INTEGER PK
  run_id            INTEGER FK
  product_id        TEXT FK
  source_path       TEXT
  sha256            TEXT INDEXED
  width, height     INTEGER
  created_at        TEXT

Finding
  id                INTEGER PK
  run_id            INTEGER FK
  product_id        TEXT FK
  scraped_image_id  INTEGER FK
  verdict           TEXT             -- PASS | STALE_VERSION | UNKNOWN_IMAGE | ERROR
  matched_version_id INTEGER FK NULL
  current_version_id INTEGER FK NULL
  match_method      TEXT             -- HASH_EXACT | PIXEL_DIFF | REGION_CHECK | NONE
  confidence        REAL
  diff_map_path     TEXT NULL
  regions_json      TEXT             -- [{x,y,w,h,field_key,old,new,severity}]
  severity          TEXT             -- MATERIAL | COSMETIC | UNCERTAIN | NONE
  created_at        TEXT

Acknowledgement
  id                INTEGER PK
  product_id        TEXT FK
  region_signature  TEXT INDEXED     -- see §8.6
  reference_version_id INTEGER FK
  decision          TEXT             -- ACKNOWLEDGED | ESCALATED
  note              TEXT
  created_by        TEXT
  created_at        TEXT
```

**Note on `Acknowledgement.reference_version_id`:** acknowledgements are scoped to a
reference version. When the brand approves new artwork, old acknowledgements correctly
expire and findings resurface for re-review. This is intended behaviour.

---

## 7. Milestone 1 — Synthetic corpus generator

CLI: `python -m tools.corpus generate --products 50 --out ./data/corpus`

### 7.1 Generate base artwork

For each synthetic product, render a packaging-like image (1500×1500 PNG) with Pillow:

- Brand block (large display text, coloured background panel)
- Product name and variant/flavour text
- A **nutrition table**: 6–8 rows of `label | per 100g | per serving`, small type
- An ingredients paragraph in small type
- A net weight badge
- 1–3 claim badges ("No added sugar", "Source of fibre")
- 0–2 certification marks (simple coloured geometric glyphs)

Vary fonts, colours, and layout across products so the corpus is not homogeneous.
Include some low-contrast text over a coloured background — this is a realistic hard case.

### 7.2 Generate version chains

For each product produce 2–4 versions. Each step applies 1–3 edits drawn from:

| Edit type | Example | Expected severity |
|---|---|---|
| `NUMERIC_DRIFT` | sodium 450mg → 480mg | MATERIAL |
| `CLAIM_REMOVED` | delete "No added sugar" badge | MATERIAL |
| `CLAIM_ADDED` | add "High protein" badge | MATERIAL |
| `CERT_REMOVED` | delete organic mark | MATERIAL |
| `WEIGHT_CHANGE` | 500g → 450g | MATERIAL |
| `PALETTE_SHIFT` | background hue rotate 15° | COSMETIC |
| `LOGO_NUDGE` | move brand block 4px | COSMETIC |
| `NO_CHANGE` | control pair, identical | NONE |

Write ground truth to `corpus/ground_truth.json`:

```json
{
  "SKU001": {
    "versions": ["v1", "v2", "v3"],
    "current": "v3",
    "transitions": {
      "v1->v2": [
        {"type": "NUMERIC_DRIFT", "field": "sodium_mg",
         "old": "450", "new": "480", "box": [340,880,180,30],
         "severity": "MATERIAL"}
      ]
    }
  }
}
```

### 7.3 Generate marketplace variants — CRITICAL

This is what actually tests the pipeline. For each artwork version, emit the full
cross-product of realistic marketplace transformations:

```python
JPEG_QUALITIES = [95, 85, 75, 60]
SIZES          = [(1500,1500), (1200,1200), (1000,1000), (800,800)]
PADDING        = [None, "square_pad_white", "square_pad_transparent"]
FORMATS        = ["jpeg", "webp"]
EXTRAS         = ["strip_metadata", "add_exif_comment", "srgb_convert"]
```

Also emit, for each version, one **untouched byte-identical copy** — this exercises the
hash fast path.

Output layout:

```
corpus/
  references/SKU001/v1.png, v2.png, v3.png
  scraped/run_2026_01/SKU001__v2__q75__1000x1000__pad.jpg
  ground_truth.json
  variants_manifest.json    # maps every scraped file -> true source version
```

The filename encoding matters: the pipeline must never read it, but the test harness
uses it to check correctness.

### 7.4 Noise floor calibration

CLI: `python -m tools.calibrate --corpus ./data/corpus`

1. For every **unchanged** pair (same version, different marketplace transform):
   normalize both, compute per-pixel absolute difference on the luminance channel,
   record the distribution.
2. For every **changed** pair (different versions, same transform): record the
   difference distribution **inside the known changed region only**.
3. Plot both distributions on one chart, save to `calibration/noise_floor.png`.
4. Print a recommended threshold: the 99.9th percentile of the unchanged distribution.
5. Print the separation margin between the two distributions.

**If the distributions overlap significantly, print a loud warning.** That means the
approach has a real limit at that JPEG quality, and the fallback track must handle it.

Write the result to `config/thresholds.json`. The pipeline reads from there — never
hardcode the threshold.

---

## 8. Milestone 3–4 — The pipeline

### 8.1 Offline: reference processing

`python -m pipeline.references --corpus ./data/corpus`

For each product:
1. Register every artwork version: hash, dimensions, `is_current` flag.
2. For each consecutive version pair, diff them:
   - These are your own files at identical dimensions — use **direct pixel subtraction**,
     no registration needed.
   - Threshold at a low value (these files have no compression noise between them).
   - Morphological open (3×3) to remove speckle, then close (7×7) to merge adjacent
     characters into one blob.
   - Connected components → bounding boxes.
   - Discard components under 0.05% of image area.
3. Store each box as a `DiscriminatingRegion`. Populate `field_key`, `old_value`,
   `new_value`, and `severity` from `ground_truth.json` when the box overlaps a known
   edit (IoU > 0.3). In production these would come from OCR; for the MVP the corpus
   supplies them.

### 8.2 Run pipeline entry point

`python -m pipeline.run --input ./data/corpus/scraped/run_2026_01`

Freeze the current `config/thresholds.json` into `Run.config_json` at start. Process
images with a `ProcessPoolExecutor`, `workers = cpu_count()`. Write each `Finding` to the
DB as it completes — do not batch at the end, the frontend streams progress.

### 8.3 Stage 1 — Hash

SHA-256 the raw file bytes (not decoded pixels — decoding varies by library version).
Look up against all `ArtworkVersion.sha256` for that product.

Hit → `Finding(match_method=HASH_EXACT, confidence=1.0)`, skip all remaining stages.

Also check against the previous run's `ScrapedImage.sha256` for the same source path.
Hit → copy forward the previous verdict, increment `Run.images_cached`.

### 8.4 Stage 2 — Normalize

Deterministic, in this exact order:

1. Decode; if palette or RGBA, composite onto white and convert to RGB.
2. Convert to sRGB if an ICC profile is present.
3. Detect and crop uniform letterbox padding (scan inward from each edge while the row
   or column is uniform within a small tolerance).
4. Resize to the reference's dimensions. **Use `cv2.INTER_AREA` for both images, always.**
   Different interpolation on the two sides manufactures differences that do not exist.
5. Align by phase correlation (`cv2.phaseCorrelate`) and shift by the recovered offset.
   No keypoints, no homography — these are re-encoded copies, not photographs.

### 8.5 Stage 3 — Pixel diff and version identification

For each candidate `ArtworkVersion` of this product:

1. Compute `cv2.absdiff` on the **luminance** channel (JPEG subsamples chroma, so
   luminance carries far less compression noise).
2. Also compute a chroma-channel diff, weighted lower — a pure palette change must not
   be missed.
3. Count pixels exceeding the calibrated threshold.

If exactly one version has a clean diff (below the noise floor) → identified,
`match_method=PIXEL_DIFF`.

If multiple versions look clean, or none does, run **Stage 4**.

### 8.6 Stage 4 — Discriminating-region check

Crop only the `DiscriminatingRegion` boxes for the candidate versions and compare those
regions specifically. Globally the versions are indistinguishable; inside these boxes the
signal is large.

Score each candidate by how many of its discriminating regions match. Highest score wins.
`match_method=REGION_CHECK`.

For the winning version, compute `region_signature` for each differing region:

```python
signature = sha256(f"{product_id}|{round(x,-1)}|{round(y,-1)}|"
                   f"{round(w,-1)}|{round(h,-1)}|{field_key or ''}")
```

Coordinates are rounded to the nearest 10px so a small detection shift does not defeat
acknowledgement matching.

### 8.7 Stage 5 — Verdict

| Condition | Verdict | Severity |
|---|---|---|
| Matched version is current | `PASS` | `NONE` |
| Matched an older version | `STALE_VERSION` | max severity of the deltas |
| No version matched | `UNKNOWN_IMAGE` | `UNCERTAIN` |
| Pipeline exception | `ERROR` | `UNCERTAIN` |

For `STALE_VERSION`, populate `regions_json` from the `DiscriminatingRegion` records on
the path from matched version to current version. If a `region_signature` has a matching
`Acknowledgement` for the current reference version, mark that region `acknowledged: true`
— the API filters these out by default.

Save a diff heatmap PNG to `data/diffs/{run_id}/{finding_id}.png`: the changed regions as
a translucent overlay on the scraped image.

---

## 9. API (FastAPI)

```
GET    /api/products                      list + current version + last verdict
GET    /api/products/{id}                 detail + all versions + finding history
GET    /api/products/{id}/versions        version registry with thumbnails

POST   /api/runs                          start a run  {input_dir}
GET    /api/runs                          run history
GET    /api/runs/{id}                     run summary + counts by verdict
GET    /api/runs/{id}/progress            SSE stream: processed/total, live counts
GET    /api/runs/{id}/findings            filter: verdict, severity, acknowledged,
                                          product_id; sort; paginate

GET    /api/findings/{id}                 full detail incl. regions
GET    /api/findings/{id}/images          {scraped_url, matched_url, current_url,
                                           diff_overlay_url}
POST   /api/findings/{id}/acknowledge     {decision, note}
DELETE /api/findings/{id}/acknowledge     un-acknowledge

GET    /api/config/thresholds             current calibrated values
PUT    /api/config/thresholds             update (does not affect completed runs)
GET    /api/calibration                   noise-floor chart + separation margin

GET    /api/stats                         dashboard aggregates
```

Serve images from a static mount. Do not base64-encode them into JSON responses.

---

## 10. Frontend

React + Vite + TypeScript + Tailwind + TanStack Query. Client-side routing.

### 10.1 Screens

**Dashboard** — Latest run at a glance: total products, counts by verdict, severity
breakdown, how many findings await review. Trend of stale-version counts across the last
6 runs. Prominent "Start run" action. If a run is in progress, this is where its live
progress appears.

**Run progress** — Live via SSE: processed/total, images/sec, elapsed, cache hit rate,
findings appearing in a live-updating list as they are produced. The user should be able
to start reviewing before the run finishes.

**Review queue** — The primary working screen. A filterable table of findings:
- Filters: verdict, severity, acknowledged/unacknowledged, product, run
- Default filter: unacknowledged + `STALE_VERSION` + severity `MATERIAL`
- Columns: product, thumbnail, verdict, matched version → current version, severity,
  number of changed regions, match method
- Bulk-select and bulk-acknowledge
- Keyboard navigation: `j`/`k` to move, `a` to acknowledge, `Enter` to open detail

**Finding detail** — CRITICAL, this is where the product's value is delivered:
- **Image comparison viewer** with three modes, toggled: side-by-side, swipe slider
  (draggable divider over the two images), and difference overlay
- Synchronised zoom and pan across both panes
- Changed regions drawn as boxes; clicking a box zooms both panes to it
- Region list beside the viewer: field name, old value → new value, severity
- Version context: "Serving v2.1, approved is v3.0, approved 2026-03-14"
- Acknowledge / escalate with a note field
- The full delta chain when the listing is more than one version behind

**Product detail** — Version registry with thumbnails and approval dates, a visual
timeline of versions, and this product's finding history across runs.

**Settings** — Threshold values with the calibration chart alongside, so the numbers have
context. Editing thresholds must warn that completed runs are unaffected.

### 10.2 Design direction

Do not ship the default AI-app look. Specifically avoid: cream background with a serif
display face and a terracotta accent; near-black with a single acid accent; generic card
grids with soft shadows everywhere.

This is a dense, professional review tool used for long sessions. Bias toward:
- High information density; the review queue should show many rows without scrolling
- A restrained palette where **colour carries meaning only** — severity and verdict are
  the only things that should be coloured. Everything else is neutral.
- A tabular/monospace face for values, versions, and hashes; a clean grotesque for UI
- The image comparison viewer is the signature element. Spend the design effort there and
  keep everything around it quiet.

Quality floor, unannounced: responsive to tablet width, visible keyboard focus rings,
`prefers-reduced-motion` respected, empty states that tell the user what to do next,
errors that say what happened and how to fix it.

Copy rules: active voice, sentence case, consistent verbs (a button that says
"Acknowledge" produces a toast that says "Acknowledged"). Name things by what the user
controls, not by how the system works.

---

## 11. Acceptance tests

```
test_hash_exact_match
    Untouched byte copy is identified with confidence 1.0 via HASH_EXACT.

test_version_identification_across_transforms
    Every file in variants_manifest.json is matched to its true source version.
    Report accuracy broken down by JPEG quality and by output size.
    PASS threshold: >98% at q>=75.

test_no_false_positives_on_reencoding
    Unchanged artwork re-encoded at all qualities produces verdict PASS.
    PASS threshold: zero false positives at q>=75.
    This is the most important test in the suite. A tool that cries wolf is abandoned.

test_numeric_drift_detected
    Every NUMERIC_DRIFT edit in ground_truth is reported, with the correct region
    and the correct old->new values.

test_cosmetic_not_flagged_as_material
    PALETTE_SHIFT and LOGO_NUDGE are classified COSMETIC, not MATERIAL.

test_determinism
    Run the pipeline twice over the same input. Assert findings are byte-identical
    (excluding ids and timestamps).

test_acknowledgement_suppression
    Acknowledge a finding, re-run, confirm it does not appear in the default queue.

test_acknowledgement_expires_on_new_version
    Add a new current version, re-run, confirm previously acknowledged findings
    resurface.

test_cache_hit_rate
    Re-run identical input; assert images_cached == images_total.
```

---

## 12. Tech stack

**Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.x, SQLite, OpenCV
(`opencv-python-headless`), NumPy, Pillow, `scikit-image`, pytest.

**Frontend:** React 18, Vite, TypeScript, Tailwind, TanStack Query, TanStack Table,
Recharts.

Do not add: Docker, Celery, Redis, Postgres, auth libraries, ORM migrations tooling.
Keep the MVP runnable with `uvicorn` plus `npm run dev`.

**Repo layout:**

```
backend/
  pipeline/    references.py  run.py  normalize.py  diff.py  verdict.py
  api/         main.py  routes/  schemas.py
  db/          models.py  session.py
  tools/       corpus.py  calibrate.py
  tests/
frontend/
  src/         pages/  components/  api/  lib/
data/          corpus/  diffs/  db.sqlite
config/        thresholds.json
```

---

## 13. Deliverables

1. Working `python -m tools.corpus generate` producing corpus + ground truth
2. Working `python -m tools.calibrate` producing the noise-floor chart and thresholds
3. Working end-to-end run over the synthetic corpus
4. All acceptance tests in §11 passing, with the accuracy breakdown printed
5. Frontend covering every screen in §10
6. `README.md` with setup, the three commands to run the demo, and a short
   "how version identification works" section
7. A `RESULTS.md` reporting measured accuracy by JPEG quality and image size, and the
   calibrated noise-floor threshold with the separation margin

Report honestly in `RESULTS.md` where the approach breaks down — the quality/size
combinations where detection fails are the most useful output of this MVP, because they
define where the photograph fallback track will need to take over.