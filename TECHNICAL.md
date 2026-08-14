# Technical reference

Everything in this build: the architecture, every module, every algorithm, every
threshold and why it has the value it has.

Companion documents: [USER-GUIDE.md](USER-GUIDE.md) for operation,
[RESULTS.md](RESULTS.md) for measured accuracy, [README.md](README.md) for the
short version.

---

**New to this?** Read [Start here — the whole system in plain words](#start-here--the-whole-system-in-plain-words)
below, then come back to the numbered sections for the detail. Every piece of
jargon used anywhere in this document is defined in the
[Glossary](#17-glossary), and terms are linked to it on first use.

---

## Table of contents

- [Start here — the whole system in plain words](#start-here--the-whole-system-in-plain-words)

1. [The core insight](#1-the-core-insight)
2. [System architecture](#2-system-architecture)
3. [Data model](#3-data-model)
4. [Milestone 1 — corpus generation](#4-milestone-1--corpus-generation)
5. [Milestone 2 — calibration](#5-milestone-2--calibration)
6. [Milestone 3 — reference processing](#6-milestone-3--reference-processing)
7. [Milestone 4 — the run pipeline](#7-milestone-4--the-run-pipeline)
8. [The algorithms in detail](#8-the-algorithms-in-detail)
9. [Configuration reference](#9-configuration-reference)
10. [API reference](#10-api-reference)
11. [Frontend architecture](#11-frontend-architecture)
12. [Determinism, caching and concurrency](#12-determinism-caching-and-concurrency)
13. [Test suite](#13-test-suite)
14. [Deviations from the spec](#14-deviations-from-the-spec)
15. [Bugs found during the build](#15-bugs-found-during-the-build)
16. [What would need to change for production](#16-what-would-need-to-change-for-production)
17. [Glossary](#17-glossary)

---

## Start here — the whole system in plain words

### The problem

A brand corrects a number on a pack — sodium goes from 450mg to 480mg. New artwork
is approved and sent to every marketplace. Most listings update. Some don't.

Six months later a storefront is still showing the **old** picture, with the **old**
number on it. That is a regulatory exposure. Nobody catches it, because the listing
doesn't look broken — it looks like a perfectly normal product page. You would only
find it by opening 15,000 listings and squinting at the nutrition panel on each one.

This tool opens the 15,000 listings and squints, once a month.

### The one idea everything else follows from

The image on the listing page is **not a photograph of the box**. It is the brand's
own artwork file — the marketplace just took that file, shrank it, and re-saved it
as a JPEG.

That changes the question completely. It is not *"do these two images look similar?"*
— a vague question with a fuzzy answer. It is:

> **Which one of our four known artwork files is this listing serving a copy of?**

That has an exact answer, and there are only ever a handful of possibilities. The
useful mental model is a **photocopy of an ID card**. The photocopy is smudged, grey
and slightly crooked, so you can't compare it pixel-for-pixel against the original.
But you have the four ID cards it *could* have been copied from, and only one of them
has "480" where the photocopy has "480". You don't need to measure similarity. You
need to find which one it came from — and to say "I can't tell" when the smudge is
too heavy to be sure.

Everything below is machinery for answering that question cheaply and honestly.

### Why the obvious approach fails

The obvious approach is: subtract the two images, see how different they are, pick
the closest one. It does not work, and it's worth understanding exactly why, because
the whole architecture is a response to it.

**The change you're hunting is smaller than the damage the marketplace does.**
Changing `450mg` to `480mg` alters maybe 300 pixels out of 2,250,000 — about
**0.013%** of the image. Meanwhile, saving that image as a JPEG nudges *every single
pixel* by a small random amount. So "v3 vs v4" and "v4 vs a re-saved v4" produce
difference numbers in the same range. The signal is quieter than the noise.

It's trying to hear one whispered word while standing next to a motorway. Turning up
the volume doesn't help — you amplify the traffic too.

**So the tool never compares the whole image when it matters.** Instead it does two
things.

**First: only look where it can possibly matter.** Before any listing is checked,
the tool compares *our own artwork files against each other* — v1 against v2, v2
against v3, v3 against v4. Those are clean files with no compression between them, so
the differences are exact. It records the boxes: *"v3 and v4 differ here, here and
here, and nowhere else."* Those boxes are called **discriminating regions** —
literally, the only places on the pack where the versions can be told apart. When a
listing image arrives, the tool ignores 98% of the pack and looks only inside those
boxes.

**Second: compare the candidates against each other, not against a fixed bar.** This
is the part that actually makes it work. Every candidate version is being compared
against the *same* blurry listing image, so every candidate suffers the *same* JPEG
damage in the *same* boxes. When you compare candidates to each other, that shared
damage is a common term and cancels out.

It's marking a brutally hard exam. Nobody scored well in absolute terms, so a fixed
pass mark tells you nothing — but the ranking is still perfectly informative. The
tool asks *"which version looks least changed inside the boxes where versions
change?"* and takes the winner. The one that looks unchanged where change was
guaranteed is the one being served.

### The four-step walkthrough

Here is a single listing image going through the system.

**Step 0 — done once, when artwork is approved.** Register every approved artwork
file: its path, its dimensions, and a [hash](#17-glossary) of its bytes. Then diff
each consecutive pair and store the discriminating regions. This is the "cheat sheet"
every later check reads from.

**Step 1 — is it byte-for-byte identical?** Take a [SHA-256](#17-glossary) of the
downloaded file — a fingerprint of its exact bytes — and look it up against the
registered artwork. If it matches, you are done, and this isn't an estimate, it's
*proof*: the marketplace is serving your file unmodified. Confidence 1.00, no
comparison performed. This resolves about 6% of a run instantly.

**Step 2 — clean the image up.** Marketplaces pad images into squares with white
bars, convert colour profiles, and flatten transparency. None of that is a real
difference, so it's undone first: convert colour to a standard, flatten any
transparency onto white, then find where the padding stops and the artwork starts and
cut the padding away. This step is fussier than it sounds and §8.2 explains why —
getting the boundary wrong by half a pixel puts a glowing outline around every letter
on the pack, and that outline is *far* bigger than the change you're looking for.

**Step 3 — the cheap screen.** Compare the whole cleaned image against each candidate
version. If exactly one candidate comes back essentially identical and the others are
obviously different, take it. This only fires when versions differ *grossly* — a
whole-pack colour change, say. It resolves about 35 images out of 2,125. It's kept
because when it does fire it's nearly free.

**Step 4 — the real test.** For each candidate version, look inside that version's
discriminating regions and measure how much the listing differs from it *there*.
Add those up per candidate. Sort. The lowest total wins — that's the version the
listing looks unchanged against, in exactly the places where versions differ.

Then the honesty check: the winner must beat the runner-up by at least **12%**. If
the top two are within 12% of each other, the tool has essentially flipped a coin, so
it declines to answer and reports **Not identified**. This stage handles 1,948 of
2,125 images at 100% accuracy.

**Step 5 — turn the answer into a verdict.**

- Matched the current approved version → **Current**. Nothing to do.
- Matched an older version → **Stale artwork**. The tool then walks the version chain
  from what's being served up to what should be, and lists *every* change along the
  way — so a listing three versions behind reports everything that's happened since,
  not just the last hop.
- Matched nothing → **Not identified**. Usually a third-party seller who photographed
  the box themselves, which is a different problem needing different maths.

### Why "I don't know" is a feature

The tool refuses to answer whenever the evidence is thin, and this is deliberate.

There are two ways to be wrong, and they cost wildly different amounts. Reporting a
*good* listing as stale — a **false alarm** — sends someone to investigate a
non-problem. Do that a few times and the team stops trusting the tool, and then it
gets ignored, and then it gets switched off. Refusing to answer just costs one person
one look at one image.

So the threshold is set at the tightest value that produces **zero** false alarms,
and accuracy takes whatever is left over — which turns out to be 99.2%. The measured
justification: on images the tool accepts, it is right **100%** of the time; on the
images it refuses, its best guess would have been right only **62.5%** of the time.
Those are two genuinely different populations, and mixing them would be dishonest.

### Where the numbers come from

No threshold in this system was guessed or hand-tuned. There is a calibration step
that measures the thing directly: take images that are definitely unchanged and see
how far their pixels move anyway, purely from re-encoding. That distribution is the
**noise floor**. Take images with a known real edit and see how far *those* pixels
move. The threshold goes where the two populations separate.

That measurement is what produced the "brightness threshold 89, colour threshold 29"
pair, and it also revealed that those two numbers *had* to be separate — a colour
shift barely moves brightness at all, so a single threshold set from brightness is
completely blind to a repainted pack. That was found by measurement, after 28 images
came back unidentified.

### What it costs to run

16 images per second on a 16-core machine, so a 15,000-image monthly run is about 16
minutes, using about 400MB of memory. Runs are incremental — an image whose bytes
haven't changed, for a product whose approved artwork hasn't changed either, keeps
its previous verdict instead of being re-checked. Approve new artwork and every
listing for that product is automatically re-opened, because the same bytes now have
a different answer.

### The one-paragraph version

Listing images are re-compressed copies of the brand's own artwork, so identifying
which version a listing serves is a closed-set lookup, not a similarity problem.
Because a one-number edit is smaller than JPEG noise, the system pre-computes exactly
which boxes distinguish each consecutive version pair, then ranks candidate versions
*against each other* inside only those boxes — where the shared compression noise
cancels out — and requires the winner to beat the runner-up by a calibrated margin,
refusing when it doesn't. Everything else in this document is that sentence, in
detail.

---

## 1. The core insight

Everything in this system follows from one observation:

> **The reference artwork and the scraped marketplace image originate from the same
> file.** The marketplace serves a re-encoded, resized copy of what the brand
> uploaded.

So this is **not an image similarity problem**. The question is never "how alike are
these two images?" It is:

> **Which known version of our artwork is this listing serving?**

That has an exact answer, drawn from a small closed set — the versions registered
for that product. The entire pipeline is built to find that answer cheaply, and to
refuse rather than guess when it cannot.

Three consequences follow directly, and they shape every design decision below:

**A hash match is proof.** If the bytes are identical to a registered version, that
*is* the version. It is never scored, ranked, weighted, or checked against anything
else.

**Two versions differing by one number are ~99.9% identical globally.** That is
*below the noise floor of JPEG compression*. A whole-image comparison genuinely
cannot separate them — not because it is implemented poorly, but because the signal
is smaller than the noise. This is why the discriminating-region stage exists, and
why it does the overwhelming majority of the work (1,948 of 2,125 images in the
reference run).

**A closed candidate set means relative ranking beats absolute thresholds.** Since
exactly one candidate is correct and all of them carry the same compression noise in
the same boxes, comparing candidates *against each other* removes the noise as a
common term. Stage 4 exploits this, and it is the single largest reason the system
reaches 99.2%.

### What is deliberately not used

| Rejected | Why |
|---|---|
| **Perceptual hashing** (pHash / dHash) | Keeps only low-frequency DCT coefficients. At that resolution a nutrition panel is a grey smudge, and `450mg → 480mg` moves the hash by approximately zero bits. It would silently skip exactly the drift this tool exists to catch. |
| **Vision-language models** | The images are 99.9% identical; models are unreliable at spotting one changed digit across near-identical pairs, and they are non-deterministic. A compliance report that changes between runs over unchanged inputs is worthless. |
| **Raw pixel equality** | JPEG re-encoding perturbs every pixel. Every threshold here is derived empirically by `tools.calibrate`. |
| **Whole-image similarity scores** (SSIM over the full frame) | Cannot discriminate versions for the reason above — the difference is smaller than the compression noise. |

---

## 2. System architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  OFFLINE  (run when artwork is approved)                        │
│                                                                 │
│  approved artwork files                                         │
│         │                                                       │
│         ▼                                                       │
│  pipeline/references.py ──► ArtworkVersion rows (sha256, current)│
│         │                                                       │
│         └── diff consecutive pairs ──► DiscriminatingRegion rows │
│                                        (the boxes that differ)   │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│  MONTHLY RUN                                                    │
│                                                                 │
│  scraped listing images                                         │
│         │                                                       │
│         ▼                                                       │
│  pipeline/run.py    ┌── Stage 1  hash ─────────────► answer     │
│    (process pool)   ├── Stage 2  normalize                      │
│                     ├── Stage 3  whole-image diff ──► answer    │
│                     ├── Stage 4  region check ──────► answer    │
│                     └── Stage 5  verdict                        │
│         │                                                       │
│         ▼                                                       │
│  Run / ScrapedImage / Finding rows  +  diff overlays            │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│  REVIEW                                                         │
│  FastAPI  ◄──────►  React SPA  ◄──────►  Acknowledgement rows   │
└─────────────────────────────────────────────────────────────────┘
```

### Layout

Three layers, and the boundary between them is the important part. `core` is a
general image-identification engine that knows nothing about packaging.
`domains/packaging` is the adapter that gives its answers compliance meaning.
`runner` executes batches. Pointing the engine at a different problem means
supplying candidates and choosing stages — no `core` change.

```
backend/
  core/                       domain-agnostic identification
    types.py                  Candidate, CandidateSet, Probe, StageOutcome, MatchResult
    config.py                 typed EngineConfig (pydantic), flat<->nested compat
    paths.py                  filesystem layout, PIPELINE_VERSION
    context.py                MatchContext — memoized per-probe working state
    engine.py                 runs stages, collects evidence, refuses by default
    harness.py                labelled-case evaluation for any candidate set
    logging.py                structlog configuration
    stages/
      base.py                 Stage protocol + registry
      hash_exact.py           Stage 1 — byte-identical proof
      whole_image.py          Stage 3 — cheap screening
      discriminating_region.py Stage 4 — relative ranking, does most of the work
      single_candidate.py     the lone-candidate rule
      photograph_fallback.py  photograph track — interface only
    imaging/
      loader.py               decode, ICC, alpha flatten, hashing
      geometry.py             de-pad, sub-pixel edges, resample, align
      metrics.py              difference scores, region signal
      regions.py              connected components, box relations
  domains/packaging/          the compliance adapter
    registry.py               artwork versions -> CandidateSet
    identify.py               one listing, end to end
    verdict.py                PASS / STALE_VERSION / UNKNOWN_IMAGE, severity
    deltas.py                 chain walk, region signatures, box mapping
    overlay.py                diff overlay rendering, pruning
  runner/                     batch execution
    orchestrator.py           run_pipeline — discover, cache, dispatch, persist
    executor.py               process pool, worker state, worker sizing
    cache.py                  what can be carried forward
    persistence.py            batched writes
  pipeline/                   CLI entry points and back-compat shims
    run.py  references.py  config.py  normalize.py  diff.py  verdict.py
  api/
    main.py  deps.py  schemas.py  routes/
  db/
    models.py  session.py
  alembic/                    schema migrations
  tools/
    corpus.py                 synthetic corpus with exact ground truth
    calibrate.py              noise-floor measurement
    accuracy.py               ground-truth evaluation of a persisted run
    ingest.py                 build a registry manifest from real artwork
    preflight.py              check real data against the method's premises
  tests/                      12 integration + 23 unit tests
frontend/
  src/
    pages/           Dashboard  ReviewQueue  FindingDetail  Products
                     Runs  RunProgress  Settings
    components/      ImageCompare  Layout  primitives  Toast
    api/             client.ts  types.ts
    lib/             format.ts  meaning.ts
data/                corpus/  diffs/  thumbs/  db.sqlite
config/              thresholds.json      (written by tools.calibrate)
calibration/         noise_floor.png      (written by tools.calibrate)
```

### The stage contract

Identification is an ordered list of components over an immutable context:

```python
class Stage(Protocol):
    name: str
    def applicable(self, ctx: MatchContext) -> bool: ...
    def run(self, ctx: MatchContext) -> StageOutcome: ...
```

`StageOutcome.decisive` is the entire control flow. The engine returns the first
decisive answer and keeps every stage's evidence either way. Its important
property is what it cannot do: **there is no path by which a probe is accepted
because the chain ran out.** Refusal is the default and accepting requires a stage
to say so — which is exactly the guarantee the previous procedural version lacked
(§15).

`MatchContext` owns and memoizes the expensive intermediates — the normalized
probe, each prepared pair, each difference map — so reordering or adding a stage
costs nothing and no stage has to be handed another's leftovers.

### Stack

| | |
|---|---|
| Language | Python 3.11+ |
| Image processing | OpenCV, NumPy, Pillow (with ImageCms for ICC) |
| Persistence | SQLite (WAL), SQLAlchemy 2.x, Alembic migrations |
| Configuration | Pydantic v2 — validated, sectioned by consuming stage |
| Logging | structlog — key-value console, JSON under `PCM_LOG_JSON` |
| API | FastAPI, `sse-starlette` for progress streaming |
| Parallelism | `ProcessPoolExecutor` with the **spawn** context |
| Frontend | React 18, Vite, TypeScript, Tailwind 3.4, TanStack Query, Recharts, React Router |

---

## 3. Data model

`backend/db/models.py`. All timestamps are UTC ISO-8601 **strings**, so the database
stays inspectable with plain `sqlite3` and run history diffs cleanly.

### Reference side — what the brand approved

**`products`** — `id` (SKU, primary key), `name`, `brand`, `created_at`.

**`artwork_versions`** — one row per approved artwork file.

| Column | Notes |
|---|---|
| `product_id` | FK → products |
| `version_label` | e.g. `v3` |
| `file_path` | absolute path to the artwork |
| `sha256` | **indexed** — this is what Stage 1 looks up |
| `width`, `height` | reference pixel space; region coordinates are in this space |
| `is_current` | exactly one true per product |
| `approved_at` | shown in the UI as the approval date |

**`discriminating_regions`** — the boxes that distinguish one version from the next.

| Column | Notes |
|---|---|
| `from_version_id`, `to_version_id` | the consecutive pair this box separates |
| `x, y, w, h` | in `from_version` pixel space |
| `area_fraction` | box area as a fraction of the canvas |
| `field_key`, `old_value`, `new_value`, `edit_type` | from OCR in production; from the corpus here |
| `severity` | `MATERIAL` \| `COSMETIC` \| `UNKNOWN` |

These rows are **derived data** — nothing points at them, so `references.py` deletes
and rebuilds them on every run. Artwork versions are *not* rebuilt, because findings
reference them.

### Run side — what the marketplace is actually serving

**`runs`** — `status` (`RUNNING`/`COMPLETE`/`FAILED`), `pipeline_version`,
`input_dir`, `images_total`/`images_processed`/`images_cached`, `error`, and
**`config_json`** — the fully resolved threshold configuration, frozen at run start.
That last column is what makes a completed run reproducible: recalibrating later
cannot rewrite its verdicts.

**`scraped_images`** — `run_id`, `product_id`, `source_path`, `sha256`, dimensions.

**`findings`** — one per scraped image.

| Column | Values |
|---|---|
| `verdict` | `PASS` \| `STALE_VERSION` \| `UNKNOWN_IMAGE` \| `ERROR` |
| `matched_version_id` | the version the listing is serving |
| `current_version_id` | the approved version it should be serving |
| `match_method` | `HASH_EXACT` \| `PIXEL_DIFF` \| `REGION_CHECK` \| `CACHED` \| `NONE` |
| `confidence` | margin over the runner-up, 0–1 |
| `diff_map_path` | JPEG overlay, written only for stale findings |
| `regions_json` | the changed regions, denormalized for read speed |
| `severity` | `MATERIAL` \| `COSMETIC` \| `UNCERTAIN` \| `NONE` |
| `stage_trace_json` | what each stage measured and why it decided — written for everything except a clean `PASS` |

`stage_trace_json` is what makes a refusal answerable after the fact. Before it,
"why was this image not identified?" could only be answered by re-running the file
under a one-off script with that run's original thresholds. It is skipped for
passing findings because those have nothing to explain and would otherwise add
tens of megabytes per run, kept forever, for images nobody will look at.

**`acknowledgements`** — a reviewer's sign-off on **one region**, not one finding.

| Column | Notes |
|---|---|
| `product_id` | |
| `region_signature` | sha256 of `product\|x\|y\|w\|h\|field_key`, coords rounded to 10px |
| `reference_version_id` | **the scope** — approve new artwork and this expires |
| `decision` | `ACKNOWLEDGED` \| `ESCALATED` |
| `note`, `created_by`, `created_at` | |

Two design decisions here are load-bearing:

**Scoped to the reference version.** Signing off "we know this listing shows the old
sodium value" is a statement about a specific pair of artwork versions. When the
brand approves new artwork, the reference version changes, the sign-off stops
matching, and the finding correctly resurfaces.

**Resolved at read time, never stamped at write time.** Findings do not carry an
`acknowledged` flag. The API joins acknowledgements in when it serves a finding
(`api/deps.py: ack_map`, `decorate_regions`). A new run therefore inherits every
existing sign-off automatically, and revoking one takes effect everywhere at once.
The cost is that the queue's `acknowledged` filter must be applied in Python after
the SQL query, which `routes/runs.py` does explicitly.

---

## 4. Milestone 1 — corpus generation

`backend/tools/corpus.py`

```bash
python -m tools.corpus generate --products 40 --out ../data/corpus
```

There is no access to real artwork or real marketplace data, so the system is
validated against synthetic packs whose edit history is known exactly.

### The state → render → measure approach

The generator works from a `ProductState` dataclass per product, and `render(state)`
is a **pure function** of it. An edit is applied by copying the state, mutating one
field, and re-rendering.

The ground-truth box for that edit is then **measured from the actual pixel
difference between the two renders** (`diff_box`), not recorded by bookkeeping. This
makes ground truth exact by construction — the box is definitionally where the
images differ, so there is no possibility of the labels drifting from the pixels.

### What the artwork contains

A 1500×1500 pack front with brand block and logo, product name and variant, a
nutrition table (8 nutrients, per-100g and per-serving columns), claim badges, up to
4 certification marks, and a net weight. Four different font sets and randomized
palettes across products.

**Full-bleed trim ticks.** The artwork draws alternating colour segments along all
four edges:

```python
tick = 12
seg = 60
for i in range(0, CANVAS, seg):
    c = st.panel if (i // seg) % 2 == 0 else st.accent
    d.rectangle([i, 0, min(i + seg, CANVAS) - 1, tick], fill=c)
    ...
```

This is not decoration — **it is what makes the whole pipeline work.** Uniform-border
cropping (§8.2) strips uniform bands from the edges inward. Without trim ticks, real
packaging artwork with a plain coloured background is *itself* uniform at the edges,
so the crop cannot tell where marketplace padding ends and artwork begins. It would
eat into the artwork by an amount that varies with the pad colour, leaving the
reference and the scraped copy at different scales. Real packaging has bleed marks,
barcodes and edge-to-edge design that serve the same purpose.

### Edit types

| Edit | Severity | What it does |
|---|---|---|
| `NUMERIC_DRIFT` | MATERIAL | Steps one nutrient value; updates both table columns |
| `CLAIM_REMOVED` | MATERIAL | Removes a claim badge |
| `CLAIM_ADDED` | MATERIAL | Adds a claim badge |
| `CERT_REMOVED` | MATERIAL | Removes a certification mark |
| `WEIGHT_CHANGE` | MATERIAL | Changes the net weight |
| `PALETTE_SHIFT` | COSMETIC | Rotates the hue of the whole pack |
| `LOGO_NUDGE` | COSMETIC | Moves the logo a few pixels |

Edits touching the same layout group (`table`, `claims`, `certs`, `weight`, `brand`,
`global`) are limited to one per transition, so ground-truth boxes never overlap and
each detected region maps to exactly one edit. `PALETTE_SHIFT` is global and always
exclusive.

Version chains average 3–4 versions per product, and a transition may also be
`NO_CHANGE` — two byte-identical files under different labels, which is the tie case
Stage 3/4 must handle.

### Marketplace transformation space

Each version is emitted as multiple listing variants across the cross-product of:

| Dimension | Values |
|---|---|
| JPEG quality | 95, 85, 75, 60 |
| Output size | 1500², 1200², 1000², 800² |
| Padding | none, white letterbox, transparent letterbox |
| Format | JPEG, WebP |
| Extras | strip metadata, add EXIF comment, sRGB convert |

Padding is `1/12` of the padded edge — 150px per side at 1500px content. Note that
this puts the padding boundary at a **non-integer pixel** after downscaling: pad
1500 → 1800, resize to 800, and the true edge lands at 66.67. That is not an
accident of the generator; it is the realistic case, and it is what motivates the
sub-pixel edge refinement in §8.2.

Plus one **untouched byte copy** per version, which must resolve via `HASH_EXACT`.

`variants_per_version` defaults to **16** — a full 4×4 grid over quality × size. At
12 the size dimension only covered three of the four sizes and 800×800 was never
generated, which hid the system's real weak point.

### Outputs

| File | Contents |
|---|---|
| `references/<SKU>/<label>.png` | the approved artwork files |
| `scraped/run_2026_01/*.jpg\|webp\|png` | the listing images |
| `ground_truth.json` | version chains, transitions, exact edit boxes, `old`/`new`, severity |
| `variants_manifest.json` | per-file transform parameters and true source version — **for the test harness only** |
| `scraped/run_2026_01/scrape_manifest.json` | **`{filename: {product_id}}` and nothing else** |
| `products.json` | names and brands |

That last one is the scraper's output contract. It names the product and never the
version, so `discover_images()` cannot cheat by reading a filename — which is a real
risk with a synthetic corpus, and worth being structurally prevented rather than
merely avoided.

---

## 5. Milestone 2 — calibration

`backend/tools/calibrate.py`

```bash
python -m tools.calibrate --corpus ../data/corpus
```

> **In plain words.** How much does a pixel move when *nothing* changed and the image
> was merely re-saved? That amount is the noise floor, and anything below it is
> meaningless. This step measures it instead of guessing it. It compares thousands of
> pixels that are known-unchanged against thousands that are known-edited, and puts
> the threshold where the two populations stop overlapping.

The threshold separating "same artwork, re-encoded" from "artwork edited" is a
**property of the encoding pipeline**, not a number to guess. It is measured here,
written to `config/thresholds.json`, and read by everything downstream.

### Two passes

**Pass 1 — per-pixel distributions set the thresholds.** For each sampled image pair,
compare the scraped image against its true reference (the *unchanged* distribution)
and against a neighbouring version's known edit boxes (the *changed* distribution).
Accumulate luma and chroma separately, then take the **99.9th percentile of the
unchanged distribution** as each threshold.

**Pass 2 — per-image fractions set the decision rules.** With the thresholds fixed,
measure what fraction of pixels each comparison actually flags, and derive
`clean_fraction` and `region_changed_fraction` from that.

### Measured output

A **percentile** is a "what fraction falls below this" reading: the 99.9th percentile
of unchanged pixel differences is the value that 999 out of every 1,000 unchanged
pixels stay under. Setting the threshold there means noise clears it once in a
thousand pixels — rare enough for the morphological open (§8.3) to sweep away.

Over 23,040,000 unchanged pixels and 43,363,639 pixels inside known edit regions,
across 192 image pairs:

| | Luma | Chroma |
|---|---|---|
| Unchanged p50 / p99 / **p99.9** | 0 / 10 / **89** | 1 / 8 / **29** |
| Inside a real edit p50 / p90 / p99 | 5 / 13 / 83 | 7 / 11 / 84 |
| **Calibrated threshold** | **89** | **29** |
| Separation margin (changed p99 − unchanged p99.9) | **−6** | **+55** |

Three things in that table matter.

**Luma and chroma needed separate thresholds.** Their noise floors differ by ~3×.
JPEG subsamples chroma 4:2:0, but it also spends most of its bits on luma edges — so
luma noise is dominated by text outlines while chroma noise is comparatively flat. A
single threshold set from the luma floor is **blind to a palette change**: a 15°
hue rotation moves chroma by ~10 and luma by ~5, both far under an 89-unit bar. This
was found by measurement after palette shifts produced 28 `UNKNOWN_IMAGE` results.

**The luma separation margin is negative**, and the tool prints a loud warning
saying so. At the pixel level, on the hardest images, compression noise and a real
edit are genuinely not separable. The system still reaches 99.2% because
identification **never depends on that absolute threshold** — Stage 4 ranks
candidates against each other, where the shared noise cancels.

**The noise floor is strongly size-dependent and the pooled number hides it.** Per
image, the 99.9th-percentile luma difference runs p50 = 79.5, p75 = 102, max = 124 —
the easy end of the corpus is several times cleaner than the hard end. The
calibration record shows the same split by size: at 800px the median correct-match
changed fraction is 0.0029, and at 1000px and above it is exactly 0. Per-size-class
thresholds would be a reasonable next step on real data.

### Chart

`calibration/noise_floor.png` — three panels: the luma distributions, the chroma
distributions, and the per-image changed-fraction separation, with the chosen
thresholds drawn in. Served to the Settings screen.

---

## 6. Milestone 3 — reference processing

`backend/pipeline/references.py`

```bash
python -m pipeline.references --corpus ../data/corpus [--reset]
```

Runs offline, when artwork is approved. Two jobs.

### Register every version

Upsert by `(product_id, version_label)`, recording the file path, `sha256`, width,
height, `is_current`, and `approved_at`. Also generates a 320px thumbnail per
version for the UI.

**Upsert, not delete-and-recreate.** Findings hold foreign keys to
`artwork_versions`, so recreating rows breaks referential integrity — this was a
real crash on the second `references` run. A version registry is also append-mostly
by nature. A label that disappears from the registry is *retired* (`is_current =
False`), never erased, so old findings keep resolving.

`--reset` exists for the case where the corpus itself is regenerated, which
invalidates every stored verdict. It deletes findings, scraped images, runs and
acknowledgements — the last because they are scoped to reference versions that no
longer exist.

### Compute discriminating regions

> **In plain words.** This is where the cheat sheet gets written. Lay v1 and v2 on top
> of each other and note down every box where they differ; repeat for v2/v3, v3/v4.
> These boxes are the only places on the pack where the versions can be told apart,
> so they are the only places Stage 4 will ever look. Because both files are our own
> clean PNGs with no compression between them, this comparison is exact — which is
> why the thresholds here are far stricter than the ones used against listings.

For each **consecutive pair** of versions, diff our own two artwork files and record
the boxes that differ.

This is direct pixel subtraction at a low threshold (`reference_luma_threshold=10`,
`reference_chroma_threshold=10`, `reference_tolerance_radius=0`). Same dimensions, no
compression between them, perfectly registered — there is no misregistration to
forgive and no reason to blur the test.

The pipeline that turns a difference map into boxes is worth unpacking, since the same
four operations appear throughout §8. **Threshold** turns the "how different is this
pixel" map into a plain yes/no mask. **Open** erases specks — anything thinner than
the brush size disappears, which kills compression noise. **Close** does the reverse,
filling gaps, so the separate strokes of "480mg" merge into one solid blob instead of
five. **Connected components** then finds each remaining blob and draws a box around
it.

Then: threshold → open → close (25px, merging adjacent glyphs and badges into one
actionable box) → connected components → drop anything under
`min_region_area_fraction` → `collapse_if_global` (a change touching >25% of the
canvas across ≥20 components becomes one region, so a hue shift reads as *"the
palette moved"* and not fifty separate badge findings).

### Mapping regions to field metadata

Detected regions are matched to ground-truth edits by box overlap:

```python
score = max(D.iou(reg, e["box"]), D.containment(reg, e["box"]))
matched = best if best_score > 0.3 else None
```

**IoU alone is the wrong relation here**, and this was a real bug — only 58 of 223
regions mapped. One logical edit often surfaces as several components: changing a
nutrient updates both the per-100g and the per-serving column, hundreds of pixels
apart, while ground truth stores a single union bounding box. Each small component
has terrible IoU against that union. `containment` — the fraction of the detected box
lying inside the edit box — catches those, while IoU still catches the case where the
detected box is the larger one. Taking the max of both fixed it.

Unmapped regions are stored with `severity = UNKNOWN` and reported in the command's
output rather than silently dropped.

In production `field_key`/`old_value`/`new_value` come from OCR. That substitution is
the only change needed here.

---

## 7. Milestone 4 — the run pipeline

`backend/pipeline/run.py`

```bash
python -m pipeline.run --input ../data/corpus/scraped/run_2026_01 [--workers N] [--no-cache]
```

### Orchestration

1. `init_db()`, `reap_stale_runs()` — any run still `RUNNING` when a new one starts
   is by definition orphaned (only one executes at a time), so it is marked `FAILED`.
   Without this a killed run blocks every subsequent one forever behind the
   "already in progress" check.
2. `build_bundles(db)` — load every product's versions and discriminating regions
   into plain dicts. Plain dicts, not ORM objects, because these get pickled to
   worker processes.
3. `discover_images(input_dir)` — read `scrape_manifest.json` for the file→product
   mapping. Falls back to the `SKU__` filename prefix for hand-assembled directories,
   which still reads only the product, never the version.
4. Create the `Run` row with `config_json` frozen, and fire `on_start(run_id)` so an
   API client can begin streaming progress immediately.
5. Cache check against the previous completed run (§12).
6. Dispatch the rest to a process pool.
7. `prune_diff_dirs(keep=6)`, mark the run `COMPLETE`.

### The five stages, per image

`process_image()` runs in a worker process. Each stage runs **only if the cheaper one
before it could not answer.**

#### Stage 1 — hash

```python
for v in versions:
    if v["sha256"] == sha:
        # proof. not scored, not ranked, not second-guessed.
```

SHA-256 of the **raw file bytes**, not decoded pixels — decoding varies by library
version, so a pixel hash would not be stable across environments. Resolves ~6% of a
typical run at confidence 1.0.

#### Stage 2 — normalize

`normalize.normalize_scraped()`. Decode → ICC-convert to sRGB → composite alpha onto
white → detect the content rectangle to sub-pixel precision → resample onto a whole-
pixel grid. Detail in §8.2.

Resizing and alignment happen later, per-reference, because the working size depends
on which reference is being compared against.

#### Stage 3 — whole-image pixel difference

Group versions by content hash first (`_version_groups`), and compare against one
representative per group. Byte-identical versions cannot be discriminated, so ranking
them produces a tie — and a tie reads as *"no version explains this image"*, which is
exactly backwards: every version explains it.

For each representative: `prepare_pair` → `diff_score` → `changed_fraction`. A
candidate is "clean" if its changed fraction is below `clean_fraction`.

**If exactly one candidate is clean, that is the answer** (`PIXEL_DIFF`). This
resolves only ~35 of 2,125 images, and that is the spec's own premise confirmed
rather than a defect — it fires only where versions differ grossly, such as a palette
shift.

#### Stage 4 — discriminating-region check

The stage that does the real work: 1,948 of 2,125 images, at 100% accuracy.

> **In plain words.** Look only inside the boxes where versions are known to differ.
> For each candidate version, add up how changed the listing looks inside those boxes.
> The candidate with the *lowest* total wins — it is the one that looks unchanged
> exactly where change was guaranteed, which means the listing is a copy of it. Then
> demand that the winner beat the runner-up by 12%; if it doesn't, the top two are
> effectively tied, and the tool refuses rather than guessing.

```python
rscores = _stage4_region_scores(stage3, bundle, cfg, candidates)
order = sorted(rscores.items(), key=lambda kv: (kv[1], kv[0]))
best_id, best_total = order[0]
second_total = order[1][1] if len(order) > 1 else float("inf")
if best_total * cfg["region_margin_ratio"] <= second_total:
    matched_id = best_id
```

For each candidate, sum `region_signal` (§8.4) over every discriminating region for
that product, with the boxes scaled from reference space into working space. Lowest
total wins — a candidate that looks *unchanged* inside the boxes known to differ is
the version being served.

**The winner is judged against the runner-up, not against an absolute bar.** Both
candidates carry the same compression noise in the same boxes, so the difference
between them is the real signal. An absolute cutoff would have to straddle the noise
floor of the worst image in the corpus, and would then reject good matches on hard
images while accepting bad ones on easy ones. Since the noise floor varies 5× across
the corpus, that is not a tunable problem — it is structural.

If the margin gate is not cleared, the image is **refused**. See §9 for why 1.12.

#### Stage 5 — verdict

`verdict.decide()`:

| Condition | Verdict | Severity |
|---|---|---|
| exception during processing | `ERROR` | `UNCERTAIN` |
| no version matched | `UNKNOWN_IMAGE` | `UNCERTAIN` |
| matched id == current id, **or matched sha == current sha** | `PASS` | `NONE` |
| otherwise | `STALE_VERSION` | max severity of the path deltas |

That third row's second clause matters: byte-identical artwork under a different
label is still compliant artwork. A version bump that did not change the pack is not
a stale listing.

For a stale finding, `_path_deltas` walks the version chain from the matched version
to the current one and collects every discriminating region along the way — so a
listing three versions behind reports everything that has changed since, not just the
last hop. Each delta gets its `region_signature` (§8.5) and a `scraped_box` mapped
back into the original scraped image's coordinates, so the reviewer's overlay lands
where they are actually looking.

### Diff overlays

Written only for `STALE_VERSION` findings with deltas. Changed regions are drawn as a
32%-opacity fill plus a 2px border, red for material and amber for cosmetic, capped
at 1200px on the long edge and JPEG-encoded at quality 85.

Full-resolution lossless PNGs cost ~400KB per finding — at the spec's 15,000 images a
month that is several gigabytes per run, kept forever. It is also unnecessary: the
overlay is a review aid, and the viewer separately draws the regions as vectors over
the full-resolution image. Capped and JPEG-encoded it is ~40KB and visually identical
at review sizes. `prune_diff_dirs(keep=6)` bounds the rest.

---

## 8. The algorithms in detail

### 8.1 Hashing

`normalize.sha256_file` — streams the file in 1MB chunks, hashes the **raw bytes**.
Never decoded pixels: decoding depends on library versions, so a pixel hash would not
be stable across environments, and stability is the whole point of Stage 1.

### 8.2 Normalization

> **In plain words.** Undo everything the marketplace did that isn't a real
> difference: strip the white bars it padded the image with, convert the colours back
> to a standard, and flatten transparency onto white. The hard part is the *exact*
> location of the padding boundary. Get it wrong by half a pixel and the two images
> end up at very slightly different scales, which puts a bright halo around every
> letter on the pack — a halo far larger than the changed digit you're hunting.

**Decoding** (`load_rgb`): ICC-profile conversion to sRGB via `ImageCms` when a
profile is present (a malformed profile is not a reason to fail the image), palette
images promoted to RGBA, alpha composited onto **white** — matching what a
marketplace does when it flattens a transparent PNG.

**Border detection** (`detect_border_crop`) scans inward from each edge while the
row/column is uniform, and is deliberately **colour-agnostic**: it strips uniform
bands whatever their colour and keeps going through colour changes.

That is what makes the crop *consistent* between a padded marketplace copy and the
unpadded reference. A rule keyed on "is it white" would strip the pad from the padded
image and nothing from the reference, leaving the two at different scales — which
smears every glyph edge into a false difference.

Uniformity is measured as **mean absolute deviation from the line's own median**, not
max-minus-min. In plain terms: *"take the typical value of this row of pixels, then
ask how far the average pixel sits from it."* Max-minus-min asks how far the single
most extreme pixel sits from it — one freak pixel decides the answer, and JPEG
manufactures freak pixels next to every hard edge.

```python
row_dev = np.abs(f - np.median(f, axis=1, keepdims=True)).mean(axis=(1, 2))
col_dev = np.abs(f - np.median(f, axis=0, keepdims=True)).mean(axis=(0, 2))
```

Concretely: JPEG and WebP ring for several pixels either side of a hard padding edge,
so a max-minus-min test stops the scan early — by a different amount per encoder and
per quality, which is what makes it so damaging. That leaves a sliver of padding in the
crop, which becomes a scale error, which smears every glyph. A robust statistic
ignores the handful of rung pixels and finds the true edge. **This was one of the
three fixes that turned the calibration from inverted to correct.**

**Sub-pixel edge refinement** (`_subpixel_edge`): the integer scan can only say "this
row is content and the one before it was padding", so it carries up to half a pixel of
error. Marketplace padding rarely lands on a whole pixel — 1500px content padded by
an eighth and resized to 800 puts the true edge at 66.67.

The refinement finds where the deviation profile crosses the **midpoint between the
padding level and the content plateau**, both estimated as medians of four samples on
their respective sides. The midpoint, not the detection tolerance: downscaling smears
the boundary over two or three pixels, and a low fixed threshold is tripped by the
leading edge of that ramp, biasing the estimate outward by more than the error it was
meant to remove.

This single change is what let the margin gate be tightened to 1.12 — it dissolved a
standing trade-off between accuracy and false alarms.

**Resampling** (`extract_content`): a `warpAffine` with `INTER_LINEAR` onto a whole-
pixel grid. The scale is within a pixel of 1:1, so this is a sub-pixel *shift*, not a
resize, and bilinear is the right filter. Integer rectangles take a plain slice.

**Common working size** (`prepare_pair`): both images go to the **smaller** of the
two dimensions, with `INTER_AREA` on both sides. See §14 for why this deviates from
the spec.

**Alignment** (`align_translation`): phase correlation with a Hanning window,
recovering an integer `(dx, dy)`, rejected past ±24px. No keypoints, no homography —
these are re-encoded copies of one file, not photographs of a pack. Sub-pixel offsets
are rounded so the result is exactly reproducible.

### 8.3 Differencing

> **In plain words.** Instead of asking *"is this pixel the same as that pixel?"* —
> which fails the moment the two images are misaligned by a hair — ask *"is this pixel
> within the range of values found right next to that pixel?"* A one-pixel wobble then
> scores zero, because the true value is still somewhere in that neighbourhood. A
> genuinely changed digit is several pixels wide, so no amount of neighbourhood-peeking
> excuses it, and it still scores full.

**Tolerance-band differencing** (`diff_channels`) is the single most important trick
in the pipeline:

```python
b_hi = cv2.dilate(b, k).astype(np.int16)
b_lo = cv2.erode(b, k).astype(np.int16)
d = np.maximum(np.maximum(a - b_hi, b_lo - a), 0)
```

Each scraped pixel is compared against the **range** of reference values in its
r-pixel neighbourhood, scoring zero if it falls inside that band. Letterbox padding
can only ever be located to about a pixel, and the resulting sub-pixel scale error
puts a one-pixel halo around every glyph. Without the band those halos dominate the
diff and drown the signal. With it they score zero, while a changed digit — which
differs over a blob several pixels across — still scores full.

`tolerance_radius = 1` for scraped comparisons, `0` for reference-vs-reference (our
own files, pixel-aligned, nothing to forgive).

**Channel split**: luma is `d[:,:,0]`, chroma is `max(d[:,:,1], d[:,:,2])` in YCrCb.

**Luma** is brightness — how light or dark a pixel is, ignoring its colour.
**Chroma** is the colour itself, ignoring brightness. **YCrCb** is simply the colour
space that stores those separately, rather than as amounts of red, green and blue.
They are split because JPEG treats them very differently — it protects brightness
detail and throws away colour detail — so they need different thresholds. Text edits
show up mostly in luma; a repainted pack shows up almost entirely in chroma.

**Normalized score** (`diff_score`): each channel divided by its own calibrated
threshold, then the max taken. `1.0` means "exactly at the threshold", which makes
every downstream comparison threshold-free.

```python
return np.maximum(luma / cfg["luma_threshold"], chroma / cfg["chroma_threshold"])
```

**Masking** (`changed_mask`): threshold at 1.0, then morphological open. Compression
noise is salt-and-pepper at the pixel level; a real edit is a connected blob several
pixels across. A 3×3 open removes most of the former and almost none of the latter,
and is where much of the separation margin comes from.

Note the two different open sizes in the config. `morph_open = 3` for whole-image
screening, which only has to spot gross differences. `region_morph_open = 1` — no open
at all — for region checks, because a changed digit is a 2–3px stroke once the listing
has been downscaled and a 3×3 open erases it completely. That was a real bug: the
single aggressive open was wiping numeric drift in 31 of 64 region checks.

### 8.4 Region signal — the ranking statistic

> **In plain words.** This is the single number that decides the winner. For one
> candidate version and one discriminating box, it answers *"how changed does this box
> look?"* — by taking the most-changed 5% of pixels in that box and averaging them.
> Not all the pixels, because a changed digit is a tiny part of the box it sits in and
> averaging everything drowns it in unchanged background. Not a simple count of
> over-threshold pixels either, because a repainted pack moves every pixel a little
> and a count sees almost nothing.

`diff.region_signal` — the mean of a region's most-changed pixels:

```python
clipped = np.clip(sub, 0.0, cap).reshape(-1)
k = max(1, int(n * top_fraction))
return float(np.partition(clipped, n - k)[n - k:].mean())
```

Three decisions here, each measured:

**Mean signal, not fraction-over-threshold.** Counting pixels over a threshold works
for a changed word — a few pixels move a long way — but it is nearly blind to a
palette shift, where every pixel moves a little and lands just under the bar. Two
versions differing only by a hue rotation score 0.0044 and 0.0045 by pixel count,
which is a coin toss; by mean signal they score 0.24 and 1.68.

**Top 5%, not the whole box.** A changed digit occupies a few percent of its bounding
box, so a plain mean buries it under the unchanged background sharing that box. At
800×800 that costs about three points of identification accuracy. The top 5% also
behaves correctly for a global recolour, where every pixel moved and the strongest 5%
is representative.

**Clipping at 3.0.** Stops one saturated region from dominating the sum, so a small
text edit still registers against a large recoloured background.

`np.partition` rather than a full sort — O(n) instead of O(n log n), and this runs
per candidate per region per image.

### 8.5 Region signatures

> **In plain words.** When a reviewer signs off on a problem, the system needs a
> stable name for *which* problem was signed off — one that survives the box being
> redetected two pixels to the left next month. That name is a short fingerprint of
> the product, the box position and the field, with the position deliberately blurred
> to the nearest 10 pixels so small jitter maps to the same name.

`verdict.region_signature` — `sha256("product|x|y|w|h|field_key")` with coordinates
rounded to the nearest 10px.

The rounding is the point. A detector box landing a few pixels differently on a
re-run must not silently defeat a reviewer's earlier sign-off. 10px is coarse enough
to absorb detector jitter and fine enough that two genuinely different edits never
collide — the closest pair in the corpus, a nutrient's per-100g and per-serving
columns, sit 300px apart.

### 8.6 Region extraction

`extract_regions`: close (25px) → connected components with stats → drop boxes under
`min_region_area_fraction` → sort deterministically top-to-bottom then left-to-right.

The close merges adjacent glyphs into one blob so a changed number reads as a single
region rather than one region per digit. At 25px rather than the spec's 7px it also
merges a logo or a badge into one box — which is the unit a reviewer actually acts on.
It halves the region count without ever bridging two separate edits.

`collapse_if_global`: ≥20 components spanning ≥25% of the canvas collapse to a single
region. A hue shift decomposes into one component per coloured element, which is
technically accurate and useless to review.

---

## 9. Configuration reference

`config/thresholds.json`, written by `tools.calibrate`, read by everything. Defaults
live in `pipeline/config.py` and are used only before calibration has run.

| Key | Value | Source | Purpose |
|---|---|---|---|
| `luma_threshold` | **89** | calibrated | p99.9 of unchanged luma difference |
| `chroma_threshold` | **29** | calibrated | p99.9 of unchanged chroma difference |
| `clean_fraction` | **0.01748** | calibrated | Stage 3 "clean" cutoff |
| `region_changed_fraction` | **0.005** | calibrated | region-level changed cutoff |
| `tolerance_radius` | 1 | reasoned | misregistration band, in pixels |
| `region_margin_ratio` | **1.12** | measured | Stage 4 evidence gate |
| `region_signal_cap` | 3.0 | reasoned | clip per-region signal |
| `region_signal_top_fraction` | 0.05 | measured | share of pixels averaged |
| `morph_open` | 3 | reasoned | whole-image speckle removal |
| `region_morph_open` | 1 | measured | **no open** inside regions |
| `morph_close` | 25 | measured | merge glyphs and badges |
| `global_change_area_fraction` | 0.25 | reasoned | collapse-to-one coverage |
| `global_change_min_regions` | 20 | reasoned | collapse-to-one component count |
| `reference_luma_threshold` | 10 | reasoned | reference-vs-reference |
| `reference_chroma_threshold` | 10 | reasoned | reference-vs-reference |
| `reference_tolerance_radius` | 0 | reasoned | no misregistration between our own files |
| `min_region_area_fraction` | 0.00005 | measured | see §14 |
| `border_uniform_tolerance` | 10 | reasoned | MAD cutoff for "uniform" |
| `max_border_crop_fraction` | 0.30 | reasoned | never crop more than 30% per side |

### On `region_margin_ratio = 1.12`

The most consequential number in the system, and it was chosen against the right
objective rather than the obvious one.

| Value | Accuracy | False alarms |
|---|---|---|
| 1.10 | 99.40% | **2** |
| **1.12** | **99.20%** | **0** |

Loosening the gate buys accuracy and pays for it in false alarms. (Before sub-pixel
edge refinement the trade was far worse: the tightest gate that produced no false
alarms was 1.18, and it cost 97.98%.) **Reporting good
artwork as stale is the failure that gets a compliance tool switched off**, so the
gate is set to the tightest value producing none, and accuracy takes what is left
(>98% at every quality). Refusing near a tie is the right failure mode: where this
gate rejects, the ranking is barely better than a coin toss, and a foreign image — a
seller's own photograph — scores alike against every version and lands here by design.

This trade-off was much sharper before sub-pixel edge refinement (§8.2); that fix is
what made 1.12 a free choice rather than a compromise.

### Threshold provenance

`save_thresholds` writes **only what was actually calibrated**, never a snapshot of
every default. Snapshotting everything would let a stale `thresholds.json` silently
shadow later changes to the pipeline's own defaults — which happened during the build
and cost real debugging time. Reproducibility is instead guaranteed per run, by
`Run.config_json`.

---

## 10. API reference

FastAPI, all routes under `/api`. `data/` is mounted statically so the frontend can
load artwork, scraped images, overlays, thumbnails and the calibration chart.

### Runs

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/runs` | run list with verdict and severity counts |
| `GET` | `/api/runs/{id}` | one run |
| `POST` | `/api/runs` | start a run — `202`, or `409` if one is in progress |
| `GET` | `/api/runs/{id}/progress` | **SSE** stream, 0.5s poll, emits only on change |
| `GET` | `/api/runs/{id}/findings` | the paged queue |

`POST /api/runs` runs the pipeline on a worker thread (it is blocking and owns a
process pool) and reports progress through the database rather than in-memory state.
It waits up to 30s for the run row to exist so it can return the id, then returns
immediately. It rejects a missing input directory (`400`), a run already in progress
(`409`), and an empty artwork registry (`400`, with the command to fix it).

`GET /api/runs/{id}/findings` filters on `verdict[]`, `severity[]`, `acknowledged`,
`product_id`, `match_method`; sorts by `severity`/`verdict`/`product`/`confidence`/
`regions`/`id`, with `order` and `offset`/`limit`.

The sort is deliberately **two passes**:

```python
rows.sort(key=lambda r: (r.product_id, r.id))
rows.sort(key=keys.get(sort, keys["severity"]), reverse=(order == "desc"))
```

Python's sort is stable, so the secondary order is always ascending by product then
id, whichever direction the primary sort runs. Folding the id into a single
descending key instead put the highest-numbered product first and filled the entire
first page with one SKU.

### Findings

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/findings/{id}` | detail, decorated regions, version chain |
| `GET` | `/api/findings/{id}/images` | URLs for scraped / matched / current / overlay |
| `POST` | `/api/findings/{id}/acknowledge` | `{decision, note, created_by}` |
| `DELETE` | `/api/findings/{id}/acknowledge` | revoke |
| `POST` | `/api/findings/bulk-acknowledge` | `{finding_ids[], decision, note}` |

Acknowledging writes one `Acknowledgement` **per region**, scoped to
`finding.current_version_id`. Rejects findings with no regions (`400`) and findings
with no reference version to scope to (`400`).

### Products

| Method | Path |
|---|---|
| `GET` | `/api/products` — with `q` search over name, SKU and brand |
| `GET` | `/api/products/{id}` — versions plus findings across all runs |
| `GET` | `/api/products/{id}/versions` |

### System

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/config/thresholds` | current values plus calibration metadata |
| `PUT` | `/api/config/thresholds` | whitelisted keys only; sets `calibrated: false` |
| `GET` | `/api/calibration` | measured distributions and the chart URL |
| `GET` | `/api/stats` | dashboard aggregates |
| `GET` | `/api/health` | |

`PUT` validates against an `EDITABLE` whitelist, rejects non-numeric and non-positive
values, and marks the configuration as no longer purely measured. It cannot affect
completed runs, which froze their own configuration.

---

## 11. Frontend architecture

React 18 + Vite + TypeScript, Tailwind 3.4, TanStack Query for server state, React
Router, Recharts.

### Design principles

**Colour is the only signal, and it is defined once.** `lib/meaning.ts` holds every
severity and verdict style, label and explanatory hint. Nothing else in the app
assigns a hue. Only severity and verdict get one.

**Names describe what the user controls, not how the system works.**
`STALE_VERSION` → "Stale artwork". `UNKNOWN_IMAGE` → "Not identified". `HASH_EXACT` →
"Exact file match", with the hint *"The listing is serving this artwork file byte for
byte. This is proof, not an estimate."*

### `ImageCompare` — the signature component

Three modes, keyboard `1`/`2`/`3`, `0` to reset:

- **Side by side** — listing next to approved artwork, **synchronised zoom and pan**,
  so you are always looking at the same place on both.
- **Swipe** — draggable divider between the **matched** version and the **current**
  version. Both are clean renders, so what you see is the artwork change itself and
  not compression noise. Comparing listing-against-artwork here would show mostly
  JPEG artefacts.
- **Difference** — the pre-rendered overlay.

Region boxes are stored and drawn in **fractional** coordinates, so they stay correct
under any zoom, pan or display size. Clicking a box zooms to it; clicking a row in the
side panel dispatches a `pcm:focus-region` event that highlights and scrolls to the
corresponding box.

### `FindingDetail` — grouping

`groupRegions()` collapses regions that share
`field|old|new|severity|edit_type|from|to` into one row with an "N areas" note. One
edit often surfaces as several boxes — moving a logo changes its top edge, its bottom
edge and its sides, each a separate connected component. All of them belong on the
image; listing them as three identical rows reads as three problems.

### `ReviewQueue`

Filter chips, SKU box, run selector, bulk selection, and full keyboard control
(`j`/`k`/`Enter`/`x`/`a`, disabled inside text inputs and under modifier keys). The
cursor row scrolls itself into view.

### Charts

`isAnimationActive={false}` on Recharts bars. The animation never settled under
headless virtual time, which made bars invisible in screenshots — and it is also the
better default for `prefers-reduced-motion`.

---

## 12. Determinism, caching and concurrency

### Determinism

A hard requirement: a compliance report that flags different things on different runs
over unchanged inputs is worthless.

Nothing in the pipeline samples randomly. Every stage is a pure function of the input
bytes. Phase correlation offsets are rounded to integers. Region lists are sorted
top-to-bottom then left-to-right. Candidate ranking breaks ties on version id
(`key=lambda kv: (kv[1], kv[0])`). Byte-identical version groups resolve toward the
*approved* label, which is the direction that avoids a false alarm.

Verified by two tests: identical findings across two runs, and identical findings
across different worker counts.

### Caching

The cache key is **source path + file hash + the product's current approved version
id**.

That third component is the interesting one. Unchanged bytes are only safe to skip
while *the question* is also unchanged. Once the brand approves new artwork, "is this
listing stale?" has a different answer for the very same bytes, so the previous
verdict must not carry forward. Approving artwork therefore re-opens every listing for
that product automatically.

A cache hit copies the previous `Finding` forward with a new `ScrapedImage` row.
`--no-cache` bypasses it entirely.

### Concurrency

The work is split across several **processes** — separate copies of Python running at
once, one per CPU core — rather than threads, because Python threads cannot execute
Python code simultaneously. Each worker gets its own copy of the reference data and
sends plain results back.

**`ProcessPoolExecutor` with the spawn context**, not the platform default fork.
**Fork** starts a worker by cloning the current process wholesale; **spawn** starts a
fresh empty interpreter and re-imports everything. Fork is faster and, here, fatal:

```python
mp_context=multiprocessing.get_context("spawn")
```

By the time a run starts, the process has usually already decoded images with OpenCV,
which leaves its own thread pool running — and the API starts runs from a worker
thread of a threaded server. Forking a multithreaded process hands the child copies of
locks held by threads that do not exist in it, and the pool deadlocks on the first
image: **idle workers, idle parent, no error, no timeout**. The test suite hung for 32
minutes of wall time on 23 seconds of CPU before this was found. Spawn pays about a
second of start-up for a clean interpreter instead.

**`cv2.setNumThreads(1)`** in each worker — the pool already provides the parallelism,
and nested threading only causes contention.

**LRU reference cache, bounded at 8.** Decoded reference artwork is ~6.5MB per version
at 1500×1500. Caching every version a worker touches costs hundreds of megabytes per
process and, at one worker per core, exhausts memory — this was the user-reported
crash on the 40-product corpus. Tasks are dispatched in **product order**
(`known.sort(key=lambda t: (t[1], str(t[0])))`), so each worker stays on one product's
references at a time and a small LRU still hits on essentially every lookup.

**Worker count capped by memory** (`_default_workers`): one per core, but no more than
70% of available memory divided by a 150MB per-worker budget.

**Persistence stays on the parent.** Workers return plain dicts; only the parent
writes to SQLite. Concurrent SQLite writers are a poor idea and this sidesteps the
question entirely.

### Throughput

2,125 images in 134 seconds on 16 cores — roughly **16 images/second**, peak RSS
405MB. Extrapolating to ~15,000 images, a monthly run is about 16 minutes.

Spawn start-up and the bounded reference cache are what bound this rather than raw
compute. Both are deliberate trades against correctness and memory safety.

---

## 13. Test suite

`backend/tests/`, 12 tests, ~6 minutes. `conftest.py` builds a session-scoped corpus
and a per-test database in a temp directory; nothing touches `data/`.

### Identification (`test_identification.py`)

| Test | Asserts |
|---|---|
| `test_hash_exact_match` | untouched byte copies resolve via `HASH_EXACT` at confidence 1.0 |
| `test_version_identification_across_transforms` | every file in the manifest matches its true source version |
| `test_no_false_positives_on_reencoding` | **re-encoded current artwork is never reported stale, at any quality** |
| `test_numeric_drift_detected` | every `NUMERIC_DRIFT` edit is found, with the right region and `old → new` |
| `test_numeric_drift_reaches_findings` | those values survive into the persisted finding |
| `test_cosmetic_not_flagged_as_material` | `PALETTE_SHIFT` and `LOGO_NUDGE` are `COSMETIC`, never `MATERIAL` |

### Determinism (`test_determinism.py`)

| Test | Asserts |
|---|---|
| `test_determinism` | two runs over identical input produce identical findings — verdicts, severities, methods, confidences, matched versions, and every region box, field, value and signature |
| `test_determinism_is_independent_of_worker_count` | results do not depend on how work was divided between processes |

### Acknowledgement and cache (`test_acknowledgement.py`)

| Test | Asserts |
|---|---|
| `test_acknowledgement_suppression` | an acknowledged finding does not return in the default queue |
| `test_acknowledgement_expires_on_new_version` | approving new artwork expires old sign-offs and findings come back |
| `test_cache_hit_rate` | re-running identical input serves every image from cache |
| `test_cache_is_bypassed_when_artwork_changes` | a new approved version forces re-evaluation of unchanged files |

### Accuracy reporting

`tools/accuracy.py` is separate from the test suite and evaluates a persisted run
against ground truth, breaking accuracy down by JPEG quality, output size, padding,
format and match method.

It reports **false alarms** (approved artwork → `STALE_VERSION`) separately from
**refusals** (→ `UNKNOWN_IMAGE`). Collapsing those into one "error" number would hide
the only distinction that matters operationally: a refusal costs a reviewer a look, a
false alarm costs the tool its credibility.

---

## 14. Deviations from the spec

Five, each documented in the code at the point of deviation.

**1. `min_region_area_fraction` = 0.00005, not the spec's 0.0005.**
0.05% of a 1500×1500 artwork is 1,125px. A single changed digit in a nutrition panel
measures about 330px. Following the spec literally discarded 13 of 14 numeric drifts —
exactly the drift the tool exists to detect. Reference-vs-reference diffs are
noise-free (two of our own PNGs, no compression between them), so the filter only needs
to drop antialiasing speckle and can safely sit an order of magnitude lower.

**2. Both images are resized to the *smaller* dimension, not the reference's.**
`INTER_AREA` degenerates to nearest-neighbour when upscaling, so resizing an 800px
listing up to a 1500px reference manufactures blocky edge differences everywhere.
Downscaling the reference instead mirrors what the marketplace CDN actually did, and
keeps interpolation identical on both sides — which is the property the spec is
protecting.

**3. Separate luma and chroma thresholds.**
The spec implies a single threshold. Their noise floors differ by ~3×, and one
threshold set from the luma floor cannot see a palette change at all (§5).

**4. Stage 4 ranks candidates against each other, and scores by top-5% mean signal.**
The spec suggests an absolute region-changed-fraction test. The noise floor varies 5×
across the corpus, so any absolute bar is wrong for most of it; and fraction-over-
threshold is nearly blind to palette shifts (§8.4).

**5. `morph_close` = 25px, not 7px.**
7px merges adjacent characters. 25px also merges a logo or badge into one box, which
is the unit a reviewer acts on. It halves the region count without ever bridging two
separate edits — the closest pair in the corpus sit 300px apart.

Plus one addition the spec does not mention but that the method requires: **full-bleed
trim ticks on the artwork** (§4), without which uniform-border cropping cannot find
the padding boundary.

---

## 15. Bugs found during the build

Recorded because each one changed the design, and several would have been production
incidents.

| Symptom | Cause | Fix |
|---|---|---|
| **Calibration inverted** — unchanged p99.9 = 202 vs changed p50 = 5 | padded and unpadded images cropped inconsistently, leaving them at different scales | trim ticks in the artwork; MAD-based border detection; the 1px tolerance band |
| Only 58 of 223 regions mapped to ground truth | one edit yields several components, ground truth stores a union bbox — IoU is the wrong relation | match on `max(iou, containment)` |
| `NUMERIC_DRIFT` produced 1 region from 14 edits | spec's min-area = 1,125px, a changed digit is ~330px | `min_region_area_fraction` = 0.00005 |
| Numeric drift erased in 31 of 64 region checks | `morph_open = 3` wipes a 2–3px stroke | separate `region_morph_open = 1` |
| Palette shifts invisible — 28 `UNKNOWN_IMAGE` | hue rotation moves chroma ~10, luma ~5; both under one 32-unit threshold | separate calibrated luma and chroma thresholds |
| Byte-identical versions produced ties → `UNKNOWN` | ranking identical candidates can only tie, and a tie reads as "nothing explains this" | sha256 grouping + `_resolve_group` preferring the approved label |
| New code defaults silently ignored | `save_thresholds` snapshotted every default, so a stale file shadowed them | write only calibrated values |
| 800×800 never generated | `variants_per_version = 12` covered 3 of 4 sizes | default 16, full 4×4 grid |
| FK constraint failure re-running references | findings reference `artwork_versions`; delete-and-recreate breaks them | upsert by label, plus `--reset` |
| **OOM on the 40-product corpus** (user-reported) | unbounded per-worker reference cache, ~840MB × 16 workers | LRU(8), product-ordered dispatch, memory-capped worker count |
| **Disk full**, truncating source files to 0 bytes | `data/diffs` at 2.5GB — 530MB/run of full-res PNG, never pruned | JPEG at 1200px (~110MB/run) + `prune_diff_dirs(keep=6)` |
| **pytest hung 32 min wall on 23s CPU** | fork-after-OpenCV-threads deadlock, silent | `mp_context=get_context("spawn")` |
| `TypeError` on ORM row in `iou` | boxes arrive as dicts, sequences and ORM rows | `as_box()` accepting all three |
| Recharts bars invisible | animation never settled under headless virtual time | `isAnimationActive={false}` |
| Table not filling width | `theme("colors.ink")` resolves to an object, breaking the whole `@apply` rule | `theme("colors.ink.DEFAULT")` |
| Queue's first page all one SKU | id folded into a single descending sort key | two-pass stable sort |
| **Every image passed on first deployment** — a foreign product (whole-image difference 0.96) and random noise (0.62) both returned `PASS` | with one registered version there is nothing to rank against, and the lone candidate was accepted by an `elif` with no test attached. Reachable for every product on first deployment, and permanently for any product never revised — so `UNKNOWN_IMAGE` was unreachable in that state | the case became an explicit `single_candidate` stage that requires the candidate to actually resemble the probe, and the engine refuses by default rather than by falling off the end of the chain |
| Byte-identical groups reported the earliest label on the hash path | `_resolve_group` prefers the approved label, but Stage 1 returned the first sha match directly and never called it | group resolution applied uniformly, so bytes identical to approved artwork report as approved |
| Content rectangle detected twice per image | `detect_content_rect` recomputed the deviation profiles that `detect_border_crop` had just measured | measure once, pass down — 32% off that step, bit-identical output |

---

## 16. What would need to change for production

**Replace `tools.corpus` with the real artwork library.** Only `references.py`'s
corpus reader changes.

**Replace `discover_images` with a real scraper.** Its contract is already defined:
a manifest mapping filename → `{product_id}`, and nothing else.

**Add OCR** for `field_key` / `old_value` / `new_value`. `references.py` already
matches detected regions to field metadata by box overlap; only the source of that
metadata changes. This will be its own significant source of error.

**Implement `pipeline/fallback.py`.** The TODO in that file specifies the method:
SIFT/AKAZE keypoints, ratio-test matching, RANSAC to a homography with rejection on
poor inlier count or condition number, warp the reference into the scraped frame, mask
to the overlap, then SSIM over local windows — because illumination and white balance
make absolute pixel differences useless for a photographed pack. Confidence must
reflect homography quality, not just the SSIM score.

**Re-derive `region_margin_ratio` against real listings.** The *method* for choosing
it — the tightest gate producing zero false alarms — is what carries over. The number
was measured on this corpus and should not be assumed.

**Consider per-size-class thresholds.** The noise floor varies 5× across the corpus
and one global threshold is a compromise across a population that is not homogeneous.

**Move off SQLite** if runs go concurrent or multi-tenant. Nothing in the pipeline
depends on SQLite specifically; the ORM layer is standard SQLAlchemy 2.x.

---

## 17. Glossary

Every term this document uses that isn't plain English. Grouped by area rather than
alphabetised, because the terms make more sense next to their neighbours.

### The vocabulary this system invented

| Term | What it means here |
|---|---|
| **Probe** | The image being identified — a downloaded listing image. |
| **Candidate** | One of the known artwork versions it might be a copy of. |
| **Candidate set** | All the versions registered for one product. Small and closed — usually 2 to 5 — which is what makes the whole approach possible. |
| **Discriminating region** | A box marking where two consecutive versions differ. The *only* places the tool looks when it matters. |
| **Region signal** | The one number that ranks candidates: how changed a listing looks inside one discriminating box, measured as the average of the most-changed 5% of its pixels. |
| **Margin / confidence** | How far the winner beat the runner-up. Not a probability — a 0.60 confidence does not mean "60% likely correct", it means the winner's score was well clear of second place. |
| **Stage** | One step in the identification chain. Each either answers decisively or passes the problem along. |
| **Refusal** | The tool declining to answer. Surfaces as **Not identified**, and is a designed outcome, not a failure. |
| **False alarm** | Reporting good, current artwork as stale. The expensive kind of mistake — the one that gets a compliance tool switched off. |
| **Noise floor** | How much pixels move when nothing changed and the image was merely re-saved. Anything below it carries no information. |

### Images and colour

| Term | What it means |
|---|---|
| **Pixel** | One dot of the image. A 1500×1500 artwork has 2.25 million of them. |
| **RGB / sRGB** | Colour stored as amounts of red, green and blue. sRGB is the standard flavour everything is converted to, so "the same colour" means the same numbers everywhere. |
| **ICC profile** | A tag embedded in an image saying which flavour of colour its numbers are in. Ignoring it makes identical artwork appear shifted in colour. |
| **Alpha channel** | Per-pixel transparency. **Compositing onto white** means replacing transparency with white — what marketplaces do, so the tool does it too, identically. |
| **Luma** | Brightness, independent of colour. |
| **Chroma** | Colour, independent of brightness. |
| **YCrCb** | A colour space storing brightness and colour separately instead of as red/green/blue. Used here because JPEG treats the two very differently. |
| **Chroma subsampling (4:2:0)** | JPEG's habit of storing colour at half resolution, since eyes notice blur in brightness far more than in colour. It's why chroma needs its own threshold. |
| **Hue** | Position on the colour wheel. A **palette shift** rotates it — every colour on the pack changes, no text moves. |
| **Lossy compression** | JPEG and WebP: they discard detail to shrink the file, so re-saving an image *always* changes its pixels. The reason nothing here can rely on exact pixel equality. |
| **Ringing / artefacts** | Faint ripples JPEG leaves beside hard edges. They're why border detection uses a robust statistic (§8.2). |
| **DCT** | The frequency transform inside JPEG. Perceptual hashes keep only its coarsest coefficients, which is why they cannot see a changed digit (§1). |
| **Letterbox / padding** | Bars added to make a rectangular image square. Not a real difference, so it's stripped before comparison. |
| **Aspect ratio** | Width divided by height. Two de-padded images from the same source must agree on it; `tools.preflight` checks exactly this. |

### Image operations

| Term | What it means |
|---|---|
| **Resample / interpolate** | Compute new pixels when resizing, since the new grid doesn't line up with the old one. |
| **INTER_AREA** | The resizing filter that averages the pixels being merged. Correct for shrinking, wrong for enlarging — where it degrades to picking one pixel and copying it (§14). |
| **INTER_LINEAR / bilinear** | Blends the four nearest pixels. Right for shifting an image by a fraction of a pixel. |
| **Sub-pixel** | Accuracy finer than one whole pixel. Padding boundaries genuinely land at fractional positions like 66.67, so integer-only detection carries built-in error. |
| **warpAffine** | Applying a shift/scale/rotate to a whole image in one operation. |
| **Phase correlation** | A frequency-domain way of finding how far one image is shifted relative to another. Cheap and exact for pure translation. |
| **Hanning window** | A soft fade applied to the image edges before phase correlation, so the hard borders don't register as a false signal. |
| **Dilate / erode** | Grow / shrink the bright areas of a mask by a brush size. |
| **Open** | Erode then dilate — removes specks smaller than the brush, leaves everything else. Used to sweep away compression noise. |
| **Close** | Dilate then erode — fills gaps smaller than the brush. Used to merge the separate strokes of a word into one box. |
| **Kernel** | The brush shape and size those operations use. `morph_open = 3` is a 3×3 brush. |
| **Connected components** | Finding each separate blob in a mask and measuring it. How difference maps become boxes. |
| **Bounding box** | The smallest rectangle enclosing a blob. Stored as `x, y, w, h`. |
| **IoU (intersection over union)** | Overlap between two boxes as a fraction of their combined area. Good for "are these the same box", bad for "is this small box part of that big one". |
| **Containment** | The fraction of one box lying inside another. Catches exactly the case IoU misses (§6). |

### Statistics

| Term | What it means |
|---|---|
| **Median** | The middle value. Unlike an average, a few extreme values can't drag it around. |
| **Percentile (p50 / p99 / p99.9)** | The value that a given share of the data falls below. p99.9 = 999 out of 1,000 samples are under this. |
| **Mean absolute deviation (MAD)** | Average distance from the typical value. Used instead of max-minus-min because it ignores a handful of freak pixels (§8.2). |
| **Separation margin** | The gap between the "unchanged" and "edited" distributions. Negative means they overlap — which they do here for brightness, and §5 explains why the system works anyway. |
| **Clipping** | Capping a value at a maximum, so one extreme reading can't dominate a sum. |
| **Top-k selection** | Pulling out the k largest values without fully sorting. `np.partition` does it in linear time, which matters when it runs per candidate per region per image. |

### Rejected approaches (§1)

| Term | What it means |
|---|---|
| **Perceptual hash (pHash/dHash)** | A short code summarising what an image *looks like*, designed so similar images get similar codes. Useless here: it's built to ignore fine detail, and fine detail is the entire problem. |
| **SSIM** | Structural similarity — a perceptual score for "how alike do these look". Answers a question this system deliberately isn't asking. |
| **SIFT / AKAZE keypoints** | Distinctive points found in an image, matchable across different viewpoints. Needed for the photograph track, unnecessary for re-encoded copies of one file. |
| **RANSAC** | Fitting a relationship from data containing many wrong matches by repeatedly guessing and keeping the guess most points agree with. |
| **Homography** | The transform relating two views of the same flat surface. What you'd need if the "listing image" is a photo taken at an angle. |

### Engineering

| Term | What it means |
|---|---|
| **SHA-256 / hash** | A short fingerprint of a file's exact bytes. Same bytes → same fingerprint, always; different bytes → different fingerprint, in practice always. |
| **Byte-identical** | The same file, not merely the same-looking image. |
| **Process vs thread** | Processes are separate copies of the program with separate memory; threads share memory inside one. Python can't run its own code on two threads at once, so parallelism here means processes. |
| **Fork vs spawn** | Two ways to create a worker process. Fork clones the parent (fast, but inherits broken locks from a multithreaded parent). Spawn starts fresh (a second slower, and correct — §12). |
| **Deadlock** | Two parts of a program each waiting on the other forever. No error, no timeout, no output — the failure mode that cost 32 minutes of hung test time. |
| **Pickling** | Python's way of packing objects into bytes so they can be sent to another process. Why worker data is plain dicts. |
| **LRU cache** | A fixed-size cache that evicts whatever was used longest ago. Bounded at 8 decoded references here, because unbounded it ate all the memory. |
| **RSS** | How much physical memory a process actually occupies. |
| **SQLite** | A database that is a single file, with no server to run. |
| **WAL (write-ahead log)** | A SQLite mode where changes are appended to a side log first. Makes writes cheap and lets reads continue during them. |
| **fsync** | Forcing data physically onto disk. Slow, and the reason per-image commits were worth batching. |
| **ORM / SQLAlchemy** | A layer letting you work with database rows as Python objects. |
| **Migration / Alembic** | A versioned, ordered script that changes the database schema, so an existing database can be upgraded rather than rebuilt. |
| **Foreign key** | A column pointing at another table's row. Why artwork versions are updated rather than deleted and recreated — findings point at them. |
| **Upsert** | Insert if absent, update if present. |
| **Denormalized** | Storing a copy of data where it's read, trading duplication for read speed. `regions_json` is the example. |
| **Pydantic** | A library that validates configuration against a declared shape, so a bad threshold fails at load with a clear message instead of somewhere deep in the maths. |
| **structlog** | Logging as key-value fields (`run_id=3 images=2125`) rather than prose, so logs can be filtered and machine-read. |
| **FastAPI** | The Python web framework serving the API. |
| **SSE (server-sent events)** | A one-way stream from server to browser, used to push live run progress without the page polling. |
| **Determinism** | Same input always produces the same output. Non-negotiable for a compliance report, and separately tested (§13). |
| **Idempotent** | Safe to repeat. Re-running against unchanged input changes nothing. |
| **React / Vite / Tailwind / TanStack Query** | The frontend stack: UI library, build tool, styling, and server-data caching respectively. |
