# Packaging compliance monitor

Marketplace listings drift. A brand revises a pack — a nutrition value changes, a
claim is withdrawn, a certification mark expires — but the storefront keeps serving
the old artwork. This tool runs monthly, works out **which approved artwork version
each listing is currently serving**, and reports exactly what is wrong with it.

| Document | For |
|---|---|
| [USER-GUIDE.md](USER-GUIDE.md) | Running it, every screen, every verdict, monthly operation |
| [TECHNICAL.md](TECHNICAL.md) | Architecture, algorithms, data model, API, every threshold and why |
| [RESULTS.md](RESULTS.md) | Measured accuracy, calibration, where the approach breaks down |

---

## Setup

Requires Python 3.11+ and Node 18+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

cd frontend && npm install && cd ..
```

## The three commands to run the demo

From the `backend/` directory, with the virtualenv active:

```bash
# 1. Build a synthetic corpus with exact ground truth (~2 min)
python -m tools.corpus generate --products 40 --out ../data/corpus

# 2. Measure the noise floor and derive thresholds (~3 min)
python -m tools.calibrate --corpus ../data/corpus

# 3. Register the approved artwork, then check the listings (~4 min)
python -m pipeline.references --corpus ../data/corpus --reset
python -m pipeline.run --input ../data/corpus/scraped/run_2026_01
```

Then report measured accuracy against ground truth:

```bash
python -m tools.accuracy --corpus ../data/corpus
```

## Running the app

```bash
# terminal 1 — from backend/
uvicorn api.main:app --port 8000

# terminal 2 — from frontend/
npm run dev        # http://localhost:5173
```

## Running the tests

```bash
cd backend && python -m pytest tests/ -v
```

The suite generates its own corpus and database in a temp directory; it does not
touch `data/`.

---

## How version identification works

**This is not an image similarity problem.** The reference artwork and the scraped
marketplace image originate from the same file — the marketplace serves a
re-encoded, resized copy of what the brand uploaded. So the question is never "do
these look similar?" It is:

> Which known version of our artwork is this listing serving?

That has an exact answer. The pipeline is built to find it cheaply, and only falls
back to fuzzier methods when no exact answer exists.

### The stages

Each stage runs only if the cheaper one before it could not answer.

**1. Hash.** SHA-256 of the raw file bytes, looked up against every registered
artwork version. A match is *proof* of which file is being served — it is never
scored, ranked, or second-guessed. About 6% of a typical run resolves here.

**2. Normalize.** Decode, composite transparency onto white, convert to sRGB,
detect and remove the marketplace's letterbox padding, then bring both images to a
common size with identical interpolation. Every step is a pure function of the input
bytes, because a compliance report that flags different things on different runs
over unchanged inputs is worthless.

**3. Whole-image pixel difference.** Compare against each candidate version.
Luminance and chroma are thresholded separately — their noise floors differ by
roughly 3×, and a single threshold set from the luma floor cannot see a palette
change at all. If exactly one version comes back clean, that is the answer.

**4. Discriminating-region check.** Two artwork versions that differ by one number
are ~99.9% identical globally, which is *below the noise floor of JPEG compression*
— a whole-image comparison genuinely cannot separate them. So the comparison happens
inside the specific boxes known to differ between versions, computed offline by
diffing the brand's own artwork files against each other. Candidates are ranked
against each other rather than against an absolute bar: both carry the same
compression noise in the same boxes, so the difference between them is the signal.

**5. Verdict.** Matched the current version → `PASS`. Matched an older one →
`STALE_VERSION`, with the field-level deltas along the path from that version to the
approved one. Nothing matched decisively → `UNKNOWN_IMAGE`, which routes to the
photograph fallback track (interface defined, not implemented).

### What it deliberately does not do

- **No perceptual hashing.** pHash keeps only low-frequency DCT coefficients; at
  that resolution a nutrition panel is a grey smudge and 450mg → 480mg moves the
  hash by approximately zero bits. It would silently skip exactly the drift this
  tool exists to detect.
- **No vision-language model.** The images are 99.9% identical, models are
  unreliable at spotting one changed digit across near-identical pairs, and they are
  non-deterministic.
- **No raw pixel equality.** JPEG re-encoding perturbs every pixel. The threshold is
  derived empirically by `tools.calibrate`, never hardcoded and never guessed.

### Thresholds

`config/thresholds.json` is written by `tools.calibrate` from measured
distributions. The pipeline reads from there. Each run freezes the fully resolved
configuration into `Run.config_json` at start, so recalibrating later cannot rewrite
the verdicts of a completed run.

---

## Results

99.2% version identification across 2,125 transformed listing images, with **zero
false alarms**. See [RESULTS.md](RESULTS.md) for the breakdown by JPEG quality and
image size, and for the quality/size combinations where the approach breaks down.

## Layout

```
backend/
  pipeline/    references.py  run.py  normalize.py  diff.py  verdict.py
               fallback.py  config.py
  api/         main.py  deps.py  schemas.py  routes/
  db/          models.py  session.py
  tools/       corpus.py  calibrate.py  accuracy.py
  tests/
frontend/
  src/         pages/  components/  api/  lib/
data/          corpus/  diffs/  thumbs/  db.sqlite
config/        thresholds.json
calibration/   noise_floor.png
```

## Out of scope for this MVP

Web scraping (the run pipeline reads a local directory), OCR field extraction (the
corpus supplies field names and values), the photograph fallback track
(`pipeline/fallback.py` defines the interface and returns `UNKNOWN_IMAGE`),
authentication, multi-tenancy, and email alerts.
