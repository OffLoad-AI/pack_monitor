# User guide

**Packaging Compliance Monitor** — how to run it, and what everything on screen means.

For the engineering detail behind any of this, see [TECHNICAL.md](TECHNICAL.md).

---

## 1. What this tool is for

A brand revises a pack. A nutrition value is corrected, a claim is withdrawn, a
certification lapses, the net weight changes. New artwork is approved and sent to
every marketplace.

Some listings never update. Months later a storefront is still serving the old
image, with the old number on it — which is a regulatory exposure, not a cosmetic
one, and nobody notices because the listing *looks* fine.

This tool runs monthly against the images live on those listings and answers one
question per image:

> **Which approved artwork version is this listing actually serving?**

If it is the current one, the listing passes. If it is an older one, the tool
reports it as stale **and lists exactly what is wrong with it** — every field that
changed between the version being served and the version that should be, with the
old and new values.

### What it is not

It does not judge whether two images "look similar". The listing image and your
reference artwork came from the same file — the marketplace just re-encoded and
resized it. So there is an exact answer, and the tool finds it. When it cannot find
one, it says so (`Not identified`) rather than guessing.

---

## 2. Setup

Requires **Python 3.11+** and **Node 18+**.

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

cd frontend && npm install && cd ..
```

---

## 3. The three commands

Run these from the `backend/` directory with the virtualenv active. Together they
take about 9 minutes on a 16-core machine.

### Step 1 — build a corpus

```bash
python -m tools.corpus generate --products 40 --out ../data/corpus
```

Generates synthetic packaging artwork with a known edit history, then produces the
marketplace-transformed copies of it — resized, re-compressed, letterboxed,
converted to WebP. Every generated file records the artwork version it came from,
which is what makes measured accuracy possible. **The pipeline never sees that
record.**

In production this step is replaced by your real artwork library and a real
scraper.

### Step 2 — calibrate

```bash
python -m tools.calibrate --corpus ../data/corpus
```

Measures the noise floor: how much a pixel moves when nothing changed and the image
was merely re-encoded, versus how much it moves when the artwork was genuinely
edited. Writes the resulting thresholds to `config/thresholds.json` and a chart to
`calibration/noise_floor.png`.

**No threshold in this system is hardcoded or guessed.** They all come from here.

### Step 3 — register artwork, then check the listings

```bash
python -m pipeline.references --corpus ../data/corpus --reset
python -m pipeline.run --input ../data/corpus/scraped/run_2026_01
```

The first command registers every approved artwork version and works out which
boxes distinguish each version from the next. The second checks every listing image
against them and writes the findings.

`--reset` clears previous run history. Use it after regenerating the corpus, and
leave it off in normal operation.

### Then: measure accuracy

```bash
python -m tools.accuracy --corpus ../data/corpus
```

Compares every verdict against ground truth and prints the breakdown by JPEG
quality, image size, padding, format and match method. This is where the numbers in
[RESULTS.md](RESULTS.md) come from.

---

## 4. Running the app

```bash
# terminal 1 — from backend/
uvicorn api.main:app --port 8000

# terminal 2 — from frontend/
npm run dev
```

Open **http://localhost:5173**.

---

## 5. Reading a verdict

Every listing image gets one of four verdicts.

| On screen | Meaning | What to do |
|---|---|---|
| **Current** | Serving the approved artwork | Nothing |
| **Stale artwork** | Serving an identified older version | Review the listed changes, then acknowledge or escalate |
| **Not identified** | No approved artwork explains this image | Usually a seller's own photograph — see below |
| **Failed** | The file could not be processed | Check the error on the detail page |

### Severity

Severity describes the *worst* change between the version being served and the
approved one.

| | Meaning | Examples |
|---|---|---|
| **Material** | A regulated or factual claim is wrong | Nutrition value, net weight, a claim, a certification mark |
| **Cosmetic** | The pack differs, but nothing factual is wrong | Palette shift, logo moved |
| **Uncertain** | The tool could not determine this | Unidentified images, errors |
| **None** | No differences | Current listings |

Work the **Material** queue first. That is the ordering the review queue defaults to.

### "Not identified" is a deliberate answer

The tool refuses rather than guesses when no version wins clearly. In practice this
means one of two things:

1. The image is **not derived from your artwork at all** — a third-party seller
   photographed the pack themselves. This is the case the photograph fallback track
   exists for, and it is not implemented in this MVP.
2. The image is so heavily downscaled and letterboxed that two candidate versions
   are genuinely indistinguishable.

Refusing is the correct behaviour here. Measured on the corpus: on images the tool
accepts, it is right 100% of the time; on images it refuses, its best guess would
have been right only 62.5% of the time. Those two populations are worth keeping
apart.

### How the match was made

Each finding records how it was identified. Hovering the label on a finding shows
the same explanation.

| Label | Meaning |
|---|---|
| **Exact file match** | The listing serves this artwork file byte for byte. Proof, not an estimate. |
| **Pixel difference** | Exactly one version differs from the listing by no more than compression noise. |
| **Region check** | Versions look alike overall, so they were compared inside the boxes known to differ. |
| **Unchanged since last run** | Both the file and the approved artwork are unchanged, so the previous verdict carries forward. |
| **No match** | Nothing explained this image. |

**Confidence** is a margin, not a probability: how far the winning version beat the
runner-up. A hash match is always 1.00.

---

## 6. The screens

### Dashboard

The state of the latest run at a glance: how many listings are current, stale,
unidentified; how many are awaiting review; a trend line across the last six runs;
and the severity split of the stale ones.

If a run is in progress it shows live and links straight to its progress view.

### Review queue

**The main working screen.** One row per finding, sorted worst-first.

Filters across the top:

- **Verdict** chips — Stale / Not identified / Failed / Current
- **Severity** chips — Material / Uncertain / Cosmetic / None
- **Unacknowledged only** toggle — on by default, so signed-off work stays out of the way
- **Product SKU** box
- **Run** selector — look at any past run, not just the latest

Columns show the thumbnail, product, verdict, severity, the version transition
(`v2 → v4`), how many regions changed, how it was matched, and the confidence.

**Keyboard shortcuts** — the queue is built to be worked without a mouse:

| Key | Action |
|---|---|
| `j` / `↓` | Next finding |
| `k` / `↑` | Previous finding |
| `Enter` | Open the finding |
| `x` | Select / deselect the row |
| `a` | Acknowledge the selection, or the row under the cursor |

Selecting rows reveals a bulk-acknowledge bar.

### Finding detail

The screen where an actual decision gets made. Left side is the image comparison,
right side is what changed and the sign-off.

**Three comparison modes** (keyboard `1`, `2`, `3`; `0` resets the view):

- **Side by side** — the listing image next to the approved artwork, zoom and pan
  locked together so you are always looking at the same place on both.
- **Swipe** — the matched version and the current approved version under a draggable
  divider. Both are clean renders, so the difference you see is the artwork change
  itself and not compression noise.
- **Difference** — the listing image with every changed region highlighted;
  red for material, amber for cosmetic.

Changed regions are drawn as boxes over the image in all modes. Click a box to zoom
to it. Click a row in the **What changed** panel to focus its box on the image.

The **Version** panel states the situation in one line — *"Serving v3, approved is
v4, approved Mar 14, 2026."* — and, when the listing is several versions behind,
shows the whole chain so you can see everything that has happened since.

The **What changed** panel lists each change with its field, its `old → new` values,
its severity, and what kind of edit it was. One edit that surfaced as several
separate boxes is grouped into one row with an "N areas" note, so three boxes from
one moved logo do not read as three problems.

**Acknowledge** or **Escalate** with an optional note. Acknowledging removes the
finding from the default queue — until new artwork is approved for that product, at
which point it comes back, because the question has changed.

### Products

Every registered product with its artwork thumbnail, version count, approval date,
last verdict and open finding count. Searchable by name, brand or SKU.

Opening a product shows its full version history, oldest to newest, and every
finding raised against it across all runs. This is the view for *"has this SKU been
a problem before?"*

### Runs

Run history: status, duration, images processed, how many came from cache, and the
verdict counts. Opening a run shows live progress while it is working, and its
findings when it is done.

### Settings

The calibrated thresholds, what each one does, and the measured separation between
the "unchanged" and "edited" distributions that produced them — plus the noise-floor
chart.

Thresholds are editable here, but the honest default is to leave them alone and
re-run `tools.calibrate` instead. Editing one marks the configuration as no longer
purely measured.

**Editing a threshold never rewrites history.** Every completed run froze its own
configuration at the moment it started, so its verdicts stay reproducible.

---

## 7. Monthly operation

1. Scrape the current listing images into a directory.
2. `python -m pipeline.run --input <that directory>` — or press **Start run** in the
   app.
3. Open the review queue, filter to **Material**, work down it.
4. Acknowledge what is understood; escalate what needs someone else.

Runs are incremental. An image whose bytes are unchanged *and* whose product still
has the same approved artwork carries its previous verdict forward instead of being
reprocessed. Approve new artwork and every listing for that product is re-opened
automatically, because the same bytes now have a different answer.

Pass `--no-cache` to force a full re-evaluation.

---

## 8. Behaviour worth knowing about

**Acknowledgements are scoped to the approved artwork.** They are attached to a
region on a product *against a specific reference version*. Approve new artwork and
every sign-off against the old one expires. This is deliberate: signing off "yes, we
know this listing shows the old sodium value" should not silently suppress a
listing once the pack changes again.

**A region's identity survives small shifts.** Region coordinates are rounded to the
nearest 10px when computing the signature that matches acknowledgements, so a
detector box landing a few pixels differently on a re-run does not quietly discard
someone's sign-off.

**A version bump that did not change the artwork is not a stale listing.** If two
approved versions are byte-identical, a listing serving either one passes.

**One run at a time.** Starting a run while one is in progress returns a conflict.
If a run was killed mid-flight, the next run marks it failed and proceeds rather
than blocking forever.

**Overlays are kept for the last six runs.** They are regenerable from the run's
inputs, and unbounded they grow into gigabytes.

---

## 9. Verifying it works

```bash
cd backend && python -m pytest tests/ -v
```

Thirty-five tests in two groups.

**Twelve integration tests**, about six minutes. They generate their own corpus and
database in a temp directory and do not touch `data/`. They cover: exact hash
identification, version identification across every transform, no false alarms on
re-encoded artwork, numeric drift detection end to end, cosmetic-vs-material
classification, determinism across runs and across worker counts, acknowledgement
suppression, acknowledgement expiry on new artwork, cache hit rate, and cache
invalidation when artwork changes.

**Twenty-three unit tests**, under a second, needing no corpus, no database and no
process pool:

```bash
python -m pytest tests/test_stages.py tests/test_config.py tests/test_harness.py -q
```

They cover each identification stage on its own, threshold configuration
round-tripping (which is what keeps completed runs reproducible), and the engine
running against a candidate set that has nothing to do with packaging — which is
the test that fails if domain assumptions leak back into the core.

Run the fast group while working and the full suite before shipping.

---

## 10. Limits of this MVP

Deliberately out of scope, stubbed rather than faked:

- **Web scraping.** The pipeline reads a local directory. The scraper's output
  contract is a manifest naming only the product per file — never the version.
- **OCR.** Field names and values come from the corpus. In production they would be
  read off the artwork, and that will be its own source of error.
- **The photograph fallback track.** `pipeline/fallback.py` defines the interface
  and returns `Not identified`. Seller-photographed packs need keypoints and a
  homography, not pixel differencing.
- **Authentication, multi-tenancy, email alerts.**

And one measured limit that is not a scope decision: **accuracy falls at 800×800
when the artwork is letterboxed** — 96.8%, against 100% at every larger size. JPEG
quality barely matters; size does. If you can request a larger asset from the
marketplace, do. Full analysis in [RESULTS.md](RESULTS.md).
