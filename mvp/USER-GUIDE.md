# User guide

How to run this tool, how to read what it tells you, and — the part that matters
most — how to tell the difference between an answer and a refusal.

Companion documents: [README.md](README.md) for setup in three commands,
[RESULTS.md](RESULTS.md) for measured accuracy, [mvp-prd.md](mvp-prd.md) for the
build specification.

---

## Contents

1. [What this tool does](#1-what-this-tool-does)
2. [Running it](#2-running-it)
3. [Comparing one pair](#3-comparing-one-pair)
4. [Comparing several pairs at once](#4-comparing-several-pairs-at-once)
5. [Reading a verdict](#5-reading-a-verdict)
6. [Reading the steps](#6-reading-the-steps)
7. [Reading a region](#7-reading-a-region)
8. [When it refuses, and why that is good](#8-when-it-refuses-and-why-that-is-good)
9. [Settings and calibration](#9-settings-and-calibration)
10. [From the command line](#10-from-the-command-line)
11. [Keyboard shortcuts](#11-keyboard-shortcuts)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. What this tool does

You give it two images:

- a **reference** — the artwork you approved, and
- a **marketplace image** — what a listing is actually showing.

It answers one question:

> Are these the same artwork — and if not, exactly what differs, in words?

Then it shows you every step it took to decide, with the pictures.

### What it is not

It is **not** the version-identification tool. That one answers a different
question — *"which of our four known artwork versions is this listing serving?"* —
across fifteen thousand listings a month, and it is much better at it. This one
takes a single pair, works far more slowly, and makes no assumption that the
marketplace image came from your file at all. It works on a photograph of a box.

Both facts matter when you read the accuracy numbers. See
[RESULTS.md](RESULTS.md), which explains why the two builds' numbers are not
comparable and should not be compared.

### What it is for

Three questions about your real data that nothing currently answers:

1. Are marketplace images re-encoded copies of your file, or photographs?
2. Can text be reliably read off real packaging — decorative type, low contrast,
   curved surfaces?
3. Does alignment succeed on real listing images at all?

Run it on real pairs and it will tell you. Those answers decide what the
production system should be.

---

## 2. Running it

Two processes: an API and a web interface.

```bash
# terminal 1 — the API
cd mvp/backend
../.venv/bin/uvicorn api.main:app --port 8000

# terminal 2 — the interface
cd mvp/frontend
npm run dev
```

Then open <http://localhost:5173>.

The header tells you two things at a glance:

| | Meaning |
|---|---|
| **reader** `rapidocr` | Which engine is reading the text. If it says `none`, no OCR is installed and every difference will come back as *needs review* rather than settled. |
| **calibrated** | Thresholds were measured from your data, not chosen by hand. |
| **hand-tuned** | Someone has edited a threshold. It is no longer a measurement. |

---

## 3. Comparing one pair

On the **Compare** screen, drop your approved artwork on the left and the
marketplace image on the right. Each drop zone shows you a thumbnail, the pixel
dimensions and the file size, so you can catch the two commonest mistakes before
you run anything: dropping the same file twice, or using a thumbnail as the
reference.

Add a label if you want one — `SKU001 front`, say. It is your note; nothing
parses it.

Press **Compare**. A single pair takes a few seconds. You will see the steps tick
past as they finish, then land on the detail screen.

---

## 4. Comparing several pairs at once

Below the drop zones, **Compare several pairs** takes a whole folder.

Name the files so they pair up:

```
ref__sku001-front.png     mkt__sku001-front.jpg
ref__sku001-back.png      mkt__sku001-back.jpg
ref__sku002-front.png     mkt__sku002-front.jpg
```

Everything before the extension, after `ref__` or `mkt__`, is the pair name. The
screen lists the pairs it found **before** you run anything, and names any file
left over rather than quietly skipping it.

Pairs run one at a time. Watch them land on the **History** screen.

---

## 5. Reading a verdict

Six answers. Three of them mean "fine", one means "there is a problem", and two
mean "I am not going to guess".

| Verdict | What it means | What to do |
|---|---|---|
| **Identical file** | The two files are byte for byte the same file. This is proof, not an estimate. | Nothing. |
| **Artwork matches** | Nothing beyond re-encoding separates them. | Nothing. |
| **Matches, with cosmetic differences** | The pack says the same thing. What differs is how it is written or coloured — the same value in a different format, or a recoloured pack. | Nothing, unless the colour itself is the point. |
| **Artwork differs** | At least one change alters what the pack *says*: a value, a unit, or a claim. | Look at the regions. This is the one that needs action. |
| **Needs review** | Something differs, but not in a way the tool can settle. | Look. It takes a few seconds and the crops are right there. |
| **Couldn't align these images** | Not enough matching detail to line the two up. Usually they show different products, or one is too low-resolution. | Check you paired the right two files. |

Next to the verdict is a **confidence**. It is the *weakest* step in the chain,
not an average — a comparison whose alignment was excellent and whose reading was
unusable is only as good as the reading. A low confidence next to a clear verdict
is telling you to look at the steps.

---

## 6. Reading the steps

The **How it decided** panel is the point of this tool. Seven steps, in order,
each expandable. Press **Step ›** to walk through them one at a time, or `j` and
`k`.

Each step shows three separate things, and they are separate on purpose:

- **Notes** — plain sentences about what the step saw. Written to be read by
  someone who has never heard of a homography.
- **Artefacts** — the pictures. On this screen the pictures are the content.
- **Measurements** — the numbers, folded away until you want them.

### Step 1 — Load and clean up

Strips the padding a marketplace added, converts colours to a standard, flattens
transparency onto white. The before/after images dim the parts that were removed
so you can check the decision, not just the result.

### Step 2 — Compare the files

Both fingerprints, in full. If they match, the marketplace is serving your file
unmodified and nothing else needs checking.

### Step 3 — Line the images up

**Look at the checkerboard.** It alternates squares from each image. If the
artwork runs continuously across a square edge, the alignment is right. If it
steps, it is not — and nothing after this step is worth reading.

The keypoint view shows the landmarks the alignment actually rests on. The
measurements tell you how many agreed, how far off they land, and how much the
reference had to be resized and rotated to fit.

### Step 4 — Find what changed

The difference map, with an opacity slider over the marketplace image. Toggle
between:

- **Over threshold** — every pixel differing by more than the measured noise floor.
- **After cleaning** — speckle removed, characters merged into words.
- **Regions read** — what survived and got handed to the reading step.

**This step is deliberately over-eager.** It proposes regions that turn out to be
nothing, because a false region costs one reading and a missed one is invisible
forever. Do not read the region count as a problem count.

### Step 5 — Read both sides

Each region cropped from both images, magnified, with what was read beneath each
one. You can check the reading yourself — that is the whole idea.

Every crop is read twice at different scales. If the two readings disagree, the
region is marked **reading unstable** and nothing it says will be treated as
evidence. With only one reference there is no second opinion available anywhere
else in the system, so the reader's own consistency is the only check there is.

### Step 6 — Compare the text

The word-level difference, with removals struck through in red and additions in
green, and a sentence saying what kind of difference it is.

### Step 7 — Decide

The rule that produced the verdict, and the changes that drove it.

---

## 7. Reading a region

The **Regions** list sits beside the inspector. Click one and it highlights in
every view that draws boxes, and jumps you to its reading.

Each region carries a severity:

| Severity | Meaning |
|---|---|
| **Material** | Changes what the pack says. A different value, unit or claim. |
| **Cosmetic** | Same meaning, written or coloured differently. |
| **Uncertain** | Real difference, not settleable automatically. |
| **No difference** | The pixels differ but the text reads the same — print and compression, not a change. |

Colour appears in this interface for exactly three things: severity, verdict, and
diff additions and removals. If something is coloured, it means something.

---

## 8. When it refuses, and why that is good

**Couldn't align these images** and **Needs review** are designed outcomes, not
failures.

There are two ways to be wrong and they cost wildly different amounts. Telling
you a good listing has changed sends someone to investigate a non-problem; do
that a few times and people stop trusting the tool, and then it gets ignored, and
then it gets switched off. Refusing costs one person one look at two crops that
are already on the screen.

So this tool declines whenever the evidence is thin. A high refusal rate is not a
defect — it is the tool being honest about a genuinely hard measurement.

The one number worth watching is **false "artwork differs"** on artwork you know
is unchanged. That is the failure that costs credibility, and
[RESULTS.md](RESULTS.md) reports it separately for exactly that reason.

---

## 9. Settings and calibration

The **Settings** screen shows every threshold beside the measurement it came
from. The chart is not decoration — it is the argument for the number.

- **Grey** is how far an image moves when *nothing* changed and it was merely
  re-saved, resized or photographed. That is the noise floor.
- **Red** is how far it moves inside a change you know about.
- The threshold sits where the two separate.

You can edit the whitelisted values. The moment you do, the badge changes from
**measured** to **hand-tuned** and stays that way until you re-measure, because a
hand-set threshold is a judgement and the screen should not go on presenting it
as a measurement.

Comparisons already run keep the values they used. Re-calibrating cannot rewrite
a verdict that has already been given.

To re-measure:

```bash
cd mvp/backend
../.venv/bin/python -m tools.calibrate --pairs ../data/pairs
```

---

## 10. From the command line

Generate a synthetic corpus with exact ground truth:

```bash
../.venv/bin/python -m tools.corpus pairs --out ../data/pairs --count 120
```

Measure the noise floor and write the thresholds:

```bash
../.venv/bin/python -m tools.calibrate --pairs ../data/pairs
```

Score the whole corpus against ground truth:

```bash
../.venv/bin/python -m tools.accuracy --pairs ../data/pairs --out ../RESULTS.json
```

Run the tests:

```bash
../.venv/bin/python -m pytest
```

---

## 11. Keyboard shortcuts

On the comparison detail screen:

| Key | Does |
|---|---|
| `j` / `↓` | Next step |
| `k` / `↑` | Previous step |
| `Esc` | Close the step, clear the selected region |

In either image pane:

| Action | Does |
|---|---|
| Scroll | Zoom, centred on the pointer |
| Drag | Pan |
| Double-click | Reset the view |

Both panes zoom and pan **together**, so you are always looking at the same part
of the pack in each.

---

## 12. Troubleshooting

**"Cannot reach the API server."**
The backend is not running. Start it with
`uvicorn api.main:app --port 8000` from `mvp/backend`.

**The header says `reader none`.**
No OCR engine is installed, so nothing can be read and every difference comes
back as *needs review*. Install one:

```bash
../.venv/bin/pip install --no-deps rapidocr-onnxruntime
../.venv/bin/pip install onnxruntime pyclipper shapely pyyaml six
```

**Every comparison says "Couldn't align these images".**
Check you are pairing the right two files. If they are right, the images may be
too low-resolution or too different in framing for landmarks to match — open the
alignment step and look at the landmark count.

**A comparison found dozens of regions.**
Expected on a photographed pack, and not a count of problems. The finding step is
deliberately generous; look at the severities in the region list instead.

**An image says "This image isn't available".**
Comparisons started from the command line keep their source images wherever they
were, outside the directory the server publishes. The step artefacts still
display normally; only the two original-file panes are affected.

**Results changed between two runs of the same pair.**
They should not — that is a defect, and there is a test for it. Check whether a
threshold was edited on the Settings screen between the runs.
