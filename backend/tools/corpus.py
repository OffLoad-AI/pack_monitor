"""Milestone 1 — synthetic packaging corpus with exact ground truth.

There is no access to real artwork or real marketplace data, so the entire system
is validated against synthetic packs whose edit history we know exactly.

The generator works from a *state* dict per product. `render(state)` is a pure
function of that state, so an edit is applied by mutating a copy of the state and
re-rendering. The ground-truth box for an edit is then measured from the actual
pixel difference between the two renders, which makes it exact by construction
rather than by bookkeeping.

    python -m tools.corpus generate --products 50 --out ./data/corpus
"""

from __future__ import annotations

import argparse
import colorsys
import json
import random
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageFont

CANVAS = 1500
PAD_FRACTION = 1 / 12  # of the padded edge, i.e. 150px per side at 1500px content

# Marketplace transformation space (§7.3).
JPEG_QUALITIES = [95, 85, 75, 60]
SIZES = [(1500, 1500), (1200, 1200), (1000, 1000), (800, 800)]
PADDING = [None, "square_pad_white", "square_pad_transparent"]
FORMATS = ["jpeg", "webp"]
EXTRAS = ["strip_metadata", "add_exif_comment", "srgb_convert"]

FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/ubuntu",
    "/usr/share/fonts/truetype/noto",
]

FONT_SETS = [
    {"display": "DejaVuSans-Bold.ttf", "ui": "DejaVuSans.ttf", "mono": "DejaVuSansMono.ttf"},
    {"display": "LiberationSans-Bold.ttf", "ui": "LiberationSans-Regular.ttf", "mono": "LiberationMono-Regular.ttf"},
    {"display": "Ubuntu-B.ttf", "ui": "Ubuntu-R.ttf", "mono": "UbuntuMono-R.ttf"},
    {"display": "LiberationSerif-Bold.ttf", "ui": "LiberationSans-Regular.ttf", "mono": "DejaVuSansMono.ttf"},
]

BRANDS = ["Yoga Bar", "Nutri Co", "Wholegrain", "Puresource", "Vital Kitchen", "Greenleaf"]
PRODUCTS = [
    ("Protein Bar", ["Choco Almond", "Peanut Butter", "Cranberry", "Coffee Cocoa"]),
    ("Muesli", ["Fruit & Nut", "Dark Chocolate", "Almond Quinoa"]),
    ("Oats", ["Rolled", "Steel Cut", "Instant Masala"]),
    ("Peanut Butter", ["Creamy", "Crunchy", "Chocolate"]),
    ("Millet Mix", ["Ragi", "Jowar", "Multi Millet"]),
    ("Breakfast Cereal", ["Honey Flakes", "Cocoa Crunch"]),
]

# label, field_key, unit, plausible value range, step used by NUMERIC_DRIFT
NUTRIENTS = [
    ("Energy", "energy_kcal", "kcal", (320, 520), 20),
    ("Protein", "protein_g", "g", (8, 24), 2),
    ("Total Fat", "fat_g", "g", (6, 28), 2),
    ("  Saturated Fat", "sat_fat_g", "g", (1, 9), 1),
    ("Carbohydrate", "carb_g", "g", (30, 68), 3),
    ("  Total Sugars", "sugar_g", "g", (2, 22), 2),
    ("Dietary Fibre", "fibre_g", "g", (3, 14), 1),
    ("Sodium", "sodium_mg", "mg", (180, 620), 30),
]

CLAIM_POOL = [
    "No added sugar", "Source of fibre", "High protein", "No palm oil",
    "Gluten free", "No preservatives", "Vegan", "Whole grain",
]
CERT_POOL = ["organic", "fssai", "vegetarian", "rainforest"]

INGREDIENT_WORDS = [
    "rolled oats", "almonds", "dates", "cocoa solids", "chicory root fibre",
    "whey protein isolate", "sunflower oil", "sea salt", "natural flavour",
    "rice crisps", "pumpkin seeds", "honey", "cashews", "cinnamon",
]

EDIT_TYPES = [
    "NUMERIC_DRIFT", "CLAIM_REMOVED", "CLAIM_ADDED", "CERT_REMOVED",
    "WEIGHT_CHANGE", "PALETTE_SHIFT", "LOGO_NUDGE",
]
SEVERITY_BY_EDIT = {
    "NUMERIC_DRIFT": "MATERIAL",
    "CLAIM_REMOVED": "MATERIAL",
    "CLAIM_ADDED": "MATERIAL",
    "CERT_REMOVED": "MATERIAL",
    "WEIGHT_CHANGE": "MATERIAL",
    "PALETTE_SHIFT": "COSMETIC",
    "LOGO_NUDGE": "COSMETIC",
    "NO_CHANGE": "NONE",
}
# Edits touching the same layout group would produce overlapping boxes, so at most
# one per transition. PALETTE_SHIFT is global and therefore always exclusive.
EDIT_GROUP = {
    "NUMERIC_DRIFT": "table",
    "CLAIM_REMOVED": "claims",
    "CLAIM_ADDED": "claims",
    "CERT_REMOVED": "certs",
    "WEIGHT_CHANGE": "weight",
    "LOGO_NUDGE": "brand",
    "PALETTE_SHIFT": "global",
}


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _find_font(name: str) -> str | None:
    for d in FONT_DIRS:
        p = Path(d) / name
        if p.exists():
            return str(p)
    return None


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    key = (name, size)
    if key not in _font_cache:
        path = _find_font(name) or _find_font("DejaVuSans.ttf")
        if path is None:
            raise RuntimeError("No usable TrueType font found; install fonts-dejavu.")
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


# --------------------------------------------------------------------------
# Colour helpers
# --------------------------------------------------------------------------


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def rotate_hue(rgb: tuple[int, int, int], degrees: float) -> tuple[int, int, int]:
    h, s, v = colorsys.rgb_to_hsv(*[c / 255 for c in rgb])
    return hsv_to_rgb(h + degrees / 360.0, s, v)


def luminance(rgb: tuple[int, int, int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def readable_ink(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    return (26, 26, 30) if luminance(bg) > 140 else (245, 245, 242)


# --------------------------------------------------------------------------
# Product state
# --------------------------------------------------------------------------


@dataclass
class ProductState:
    sku: str
    brand: str
    name: str
    variant: str
    layout: int
    fonts: dict[str, str]
    bg: tuple[int, int, int]
    panel: tuple[int, int, int]
    accent: tuple[int, int, int]
    nutrition: list[dict[str, Any]]
    ingredients: list[str]
    claims: list[str]
    certs: list[str]
    net_weight: int
    brand_offset: tuple[int, int] = (0, 0)
    low_contrast: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def copy(self) -> "ProductState":
        return ProductState(
            sku=self.sku, brand=self.brand, name=self.name, variant=self.variant,
            layout=self.layout, fonts=dict(self.fonts), bg=self.bg, panel=self.panel,
            accent=self.accent,
            nutrition=[dict(r) for r in self.nutrition],
            ingredients=list(self.ingredients),
            claims=list(self.claims), certs=list(self.certs),
            net_weight=self.net_weight, brand_offset=self.brand_offset,
            low_contrast=self.low_contrast, meta=dict(self.meta),
        )


def make_state(sku: str, rng: random.Random, index: int = 0) -> ProductState:
    brand = rng.choice(BRANDS)
    name, variants = rng.choice(PRODUCTS)
    variant = rng.choice(variants)

    # Golden-ratio hue spacing guarantees the corpus spans the wheel instead of
    # clustering wherever the RNG happens to land.
    hue = (index * 0.6180339887 + rng.random() * 0.06) % 1.0
    bg = hsv_to_rgb(hue, rng.uniform(0.28, 0.62), rng.uniform(0.55, 0.92))
    panel = hsv_to_rgb(hue + rng.uniform(-0.08, 0.08), rng.uniform(0.55, 0.85), rng.uniform(0.30, 0.55))
    accent = hsv_to_rgb(hue + 0.5, rng.uniform(0.55, 0.9), rng.uniform(0.65, 0.95))

    rows = rng.randint(6, 8)
    chosen = NUTRIENTS[:1] + rng.sample(NUTRIENTS[1:], rows - 1)
    nutrition = []
    for label, key, unit, (lo, hi), step in chosen:
        val = rng.randrange(lo, hi + 1)
        nutrition.append({
            "label": label, "key": key, "unit": unit, "value": val, "step": step,
            "serving": round(val * 0.4),
        })

    n_ing = rng.randint(6, 9)
    ingredients = rng.sample(INGREDIENT_WORDS, n_ing)

    return ProductState(
        sku=sku,
        brand=brand,
        name=name,
        variant=variant,
        layout=rng.randrange(3),
        fonts=rng.choice(FONT_SETS),
        bg=bg,
        panel=panel,
        accent=accent,
        nutrition=nutrition,
        ingredients=ingredients,
        claims=rng.sample(CLAIM_POOL, rng.randint(1, 3)),
        certs=rng.sample(CERT_POOL, rng.randint(0, 2)),
        net_weight=rng.choice([200, 250, 300, 400, 500, 750]),
        # One product in four uses low-contrast body copy over the coloured
        # background — a realistic hard case for any pixel-level method.
        low_contrast=rng.random() < 0.25,
    )


# --------------------------------------------------------------------------
# Renderer — pure function of state
# --------------------------------------------------------------------------


def _rounded(draw: ImageDraw.ImageDraw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _draw_cert(draw: ImageDraw.ImageDraw, kind: str, cx: int, cy: int, r: int, colour):
    if kind == "organic":
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=6)
        draw.ellipse([cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2], fill=colour)
    elif kind == "fssai":
        draw.rectangle([cx - r, cy - r, cx + r, cy + r], outline=colour, width=6)
        draw.line([cx - r // 2, cy, cx + r // 2, cy], fill=colour, width=6)
    elif kind == "vegetarian":
        draw.rectangle([cx - r, cy - r, cx + r, cy + r], outline=(20, 120, 40), width=6)
        draw.ellipse([cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2], fill=(20, 120, 40))
    else:  # rainforest
        draw.polygon([(cx, cy - r), (cx + r, cy + r), (cx - r, cy + r)], outline=colour, width=6)


def render(st: ProductState) -> Image.Image:
    img = Image.new("RGB", (CANVAS, CANVAS), st.bg)
    d = ImageDraw.Draw(img)

    # Full-bleed trim ticks. Real packaging artwork runs to the edge; a uniform
    # border would be genuinely indistinguishable from marketplace letterbox
    # padding, and the normalizer's uniform-border crop would eat into artwork.
    # Alternating segments keep every edge row non-uniform, so the crop stops
    # exactly at the padding boundary.
    tick = 12
    seg = 60
    for i in range(0, CANVAS, seg):
        c = st.panel if (i // seg) % 2 == 0 else st.accent
        d.rectangle([i, 0, min(i + seg, CANVAS) - 1, tick], fill=c)
        d.rectangle([i, CANVAS - 1 - tick, min(i + seg, CANVAS) - 1, CANVAS - 1], fill=c)
        d.rectangle([0, i, tick, min(i + seg, CANVAS) - 1], fill=c)
        d.rectangle([CANVAS - 1 - tick, i, CANVAS - 1, min(i + seg, CANVAS) - 1], fill=c)

    ink = readable_ink(st.bg)
    panel_ink = readable_ink(st.panel)
    f_display = st.fonts["display"]
    f_ui = st.fonts["ui"]
    f_mono = st.fonts["mono"]

    # Layout anchors vary per product so the corpus is not homogeneous.
    left = [90, 120, 80][st.layout]
    brand_y = [80, 110, 70][st.layout]
    brand_w, brand_h = 900, 190

    # --- brand block -------------------------------------------------------
    bx = left + st.brand_offset[0]
    by = brand_y + st.brand_offset[1]
    _rounded(d, [bx, by, bx + brand_w, by + brand_h], 18, fill=st.panel)
    d.text((bx + 40, by + 46), st.brand.upper(), font=font(f_display, 84), fill=panel_ink)

    # --- product name / variant -------------------------------------------
    y = brand_y + brand_h + 60
    d.text((left, y), st.name, font=font(f_display, 96), fill=ink)
    y += 118
    d.text((left, y), st.variant, font=font(f_ui, 58), fill=st.accent)

    # --- claim badges ------------------------------------------------------
    claims_y = 560
    cx = left
    for claim in st.claims:
        fnt = font(f_ui, 40)
        w = int(d.textlength(claim, font=fnt))
        _rounded(d, [cx, claims_y, cx + w + 56, claims_y + 74], 37, fill=st.accent)
        d.text((cx + 28, claims_y + 16), claim, font=fnt, fill=readable_ink(st.accent))
        cx += w + 80

    # --- certification marks ----------------------------------------------
    certs_y = 700
    ccx = left + 46
    for cert in st.certs:
        _draw_cert(d, cert, ccx, certs_y + 46, 44, ink)
        ccx += 150

    # --- nutrition table ---------------------------------------------------
    table_x, table_y = left, 830
    col_label = table_x
    col_100 = table_x + 620
    col_serv = table_x + 900
    f_head = font(f_ui, 34)
    f_row = font(f_mono, 32)

    d.text((col_label, table_y), "NUTRITION", font=font(f_display, 40), fill=ink)
    table_y += 60
    d.text((col_label, table_y), "Per pack", font=f_head, fill=ink)
    d.text((col_100, table_y), "Per 100g", font=f_head, fill=ink)
    d.text((col_serv, table_y), "Per serving", font=f_head, fill=ink)
    table_y += 46
    d.line([table_x, table_y, table_x + 1180, table_y], fill=ink, width=3)
    table_y += 14

    for row in st.nutrition:
        d.text((col_label, table_y), row["label"], font=f_row, fill=ink)
        d.text((col_100, table_y), f"{row['value']} {row['unit']}", font=f_row, fill=ink)
        d.text((col_serv, table_y), f"{row['serving']} {row['unit']}", font=f_row, fill=ink)
        table_y += 44

    # --- ingredients -------------------------------------------------------
    ing_y = table_y + 40
    body_ink = ink
    if st.low_contrast:
        # Deliberately poor contrast: body copy only slightly off the background.
        body_ink = tuple(max(0, min(255, c + (28 if luminance(st.bg) < 140 else -34))) for c in st.bg)
    f_ing = font(f_ui, 28)
    text = "INGREDIENTS: " + ", ".join(st.ingredients) + "."
    words = text.split(" ")
    line = ""
    for word in words:
        trial = (line + " " + word).strip()
        if d.textlength(trial, font=f_ing) > 980:
            d.text((left, ing_y), line, font=f_ing, fill=body_ink)
            ing_y += 38
            line = word
        else:
            line = trial
    if line:
        d.text((left, ing_y), line, font=f_ing, fill=body_ink)

    # --- net weight badge --------------------------------------------------
    wx, wy = CANVAS - 380, CANVAS - 190
    _rounded(d, [wx, wy, wx + 300, wy + 110], 14, fill=st.panel)
    d.text((wx + 26, wy + 26), f"NET {st.net_weight} g", font=font(f_display, 46), fill=panel_ink)

    return img


# --------------------------------------------------------------------------
# Edits
# --------------------------------------------------------------------------


def apply_edit(st: ProductState, edit_type: str, rng: random.Random) -> tuple[ProductState, dict] | None:
    """Return (new_state, edit_record) or None if the edit is not applicable."""
    new = st.copy()

    if edit_type == "NUMERIC_DRIFT":
        candidates = [i for i, r in enumerate(new.nutrition)]
        if not candidates:
            return None
        i = rng.choice(candidates)
        row = new.nutrition[i]
        old = row["value"]
        delta = row["step"] * rng.choice([-2, -1, 1, 2])
        row["value"] = max(1, old + delta)
        row["serving"] = round(row["value"] * 0.4)
        return new, {"type": edit_type, "field": row["key"],
                     "old": str(old), "new": str(row["value"])}

    if edit_type == "CLAIM_REMOVED":
        if not new.claims:
            return None
        claim = rng.choice(new.claims)
        new.claims.remove(claim)
        return new, {"type": edit_type, "field": "claims", "old": claim, "new": ""}

    if edit_type == "CLAIM_ADDED":
        pool = [c for c in CLAIM_POOL if c not in new.claims]
        if not pool or len(new.claims) >= 3:
            return None
        claim = rng.choice(pool)
        new.claims.append(claim)
        return new, {"type": edit_type, "field": "claims", "old": "", "new": claim}

    if edit_type == "CERT_REMOVED":
        if not new.certs:
            return None
        cert = rng.choice(new.certs)
        new.certs.remove(cert)
        return new, {"type": edit_type, "field": "certifications", "old": cert, "new": ""}

    if edit_type == "WEIGHT_CHANGE":
        old = new.net_weight
        new.net_weight = max(50, old - rng.choice([25, 50, 100]))
        return new, {"type": edit_type, "field": "net_weight_g",
                     "old": str(old), "new": str(new.net_weight)}

    if edit_type == "PALETTE_SHIFT":
        new.bg = rotate_hue(new.bg, 15)
        new.panel = rotate_hue(new.panel, 15)
        new.accent = rotate_hue(new.accent, 15)
        return new, {"type": edit_type, "field": "background_hue",
                     "old": "0deg", "new": "15deg"}

    if edit_type == "LOGO_NUDGE":
        dx, dy = rng.choice([(4, 0), (0, 4), (4, 4), (-4, 3)])
        new.brand_offset = (new.brand_offset[0] + dx, new.brand_offset[1] + dy)
        return new, {"type": edit_type, "field": "brand_block_position",
                     "old": str(st.brand_offset), "new": str(new.brand_offset)}

    return None


def diff_box(a: Image.Image, b: Image.Image) -> list[int] | None:
    """Bounding box of the pixels that differ between two renders."""
    d = np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16)).max(axis=2)
    ys, xs = np.nonzero(d > 8)
    if len(xs) == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    return [x0, y0, x1 - x0 + 1, y1 - y0 + 1]


def build_transition(
    st: ProductState, rng: random.Random
) -> tuple[ProductState, list[dict]]:
    """Apply 1-3 non-overlapping edits, measuring each edit's box in isolation."""
    if rng.random() < 0.08:
        # Control transition: artwork unchanged, version label bumped only.
        return st.copy(), [{"type": "NO_CHANGE", "field": None, "old": None,
                            "new": None, "box": None, "severity": "NONE"}]

    if rng.random() < 0.15:
        types = ["PALETTE_SHIFT"]  # global, always applied alone
    else:
        pool = [t for t in EDIT_TYPES if t != "PALETTE_SHIFT"]
        rng.shuffle(pool)
        types, groups = [], set()
        for t in pool:
            if EDIT_GROUP[t] in groups:
                continue
            types.append(t)
            groups.add(EDIT_GROUP[t])
            if len(types) >= rng.randint(1, 3):
                break

    records: list[dict] = []
    current = st

    for t in types:
        result = apply_edit(current, t, rng)
        if result is None:
            continue
        next_state, rec = result
        # Measure the box against the state immediately before this edit, so each
        # edit's ground-truth region is isolated from the others in the transition.
        box = diff_box(render(current), render(next_state))
        if box is None:
            continue
        rec["box"] = box
        rec["severity"] = SEVERITY_BY_EDIT[t]
        records.append(rec)
        current = next_state

    if not records:
        return build_transition(st, rng)
    return current, records


# --------------------------------------------------------------------------
# Marketplace variants
# --------------------------------------------------------------------------


def _srgb_profile_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def pad_square(img: Image.Image, mode: str) -> Image.Image:
    """Marketplaces re-frame artwork onto their own canvas, adding uniform padding."""
    w, h = img.size
    pad = int(round(w * PAD_FRACTION / (1 - 2 * PAD_FRACTION)))
    new_w, new_h = w + 2 * pad, h + 2 * pad
    if mode == "square_pad_transparent":
        canvas = Image.new("RGBA", (new_w, new_h), (255, 255, 255, 0))
        canvas.paste(img.convert("RGBA"), (pad, pad))
    else:
        canvas = Image.new("RGB", (new_w, new_h), (255, 255, 255))
        canvas.paste(img, (pad, pad))
    return canvas


def variant_combinations(n: int, seed: int) -> list[dict]:
    """Deterministic, stratified sample of the transformation cross-product.

    Quality and size are the two axes the accuracy report breaks down by, so they
    are walked as a full grid rather than sampled: at the default n=16 every one of
    the 4 qualities x 4 sizes appears exactly once per version. Padding, format and
    metadata handling are drawn from a seeded RNG so those combinations rotate
    across the corpus instead of correlating with a particular quality or size.
    """
    rng = random.Random(seed)
    combos = []
    for i in range(n):
        combos.append({
            "quality": JPEG_QUALITIES[i % len(JPEG_QUALITIES)],
            "size": SIZES[(i // len(JPEG_QUALITIES)) % len(SIZES)],
            "padding": rng.choice(PADDING),
            "format": rng.choice(FORMATS),
            "extra": rng.choice(EXTRAS),
        })
    return combos


def full_cross_product() -> list[dict]:
    combos = []
    for q in JPEG_QUALITIES:
        for s in SIZES:
            for p in PADDING:
                for f in FORMATS:
                    for e in EXTRAS:
                        combos.append({"quality": q, "size": s, "padding": p,
                                       "format": f, "extra": e})
    return combos


PAD_CODE = {None: "nopad", "square_pad_white": "padw", "square_pad_transparent": "padt"}


def variant_filename(sku: str, version: str, c: dict) -> str:
    w, h = c["size"]
    ext = "jpg" if c["format"] == "jpeg" else "webp"
    return (f"{sku}__{version}__q{c['quality']}__{w}x{h}__"
            f"{PAD_CODE[c['padding']]}__{c['extra']}.{ext}")


def emit_variant(ref: Image.Image, out_path: Path, c: dict) -> None:
    img = ref
    if c["padding"]:
        img = pad_square(img, c["padding"])
    img = img.resize(c["size"], Image.LANCZOS)

    save_kwargs: dict[str, Any] = {"quality": c["quality"]}
    if c["extra"] == "srgb_convert":
        save_kwargs["icc_profile"] = _srgb_profile_bytes()
    if c["extra"] == "add_exif_comment":
        exif = Image.Exif()
        exif[0x9286] = "marketplace-cdn v3"
        exif[0x010E] = f"listing asset {out_path.stem}"
        save_kwargs["exif"] = exif.tobytes()

    if c["format"] == "jpeg":
        if img.mode != "RGB":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        save_kwargs["subsampling"] = "4:2:0"
        img.save(out_path, "JPEG", **save_kwargs)
    else:
        img.save(out_path, "WEBP", **save_kwargs)


# --------------------------------------------------------------------------
# Generate
# --------------------------------------------------------------------------


def generate(out_dir: Path, n_products: int, seed: int, variants_per_version: int,
             full: bool, run_label: str) -> dict:
    out_dir = Path(out_dir)
    refs_dir = out_dir / "references"
    scraped_dir = out_dir / "scraped" / run_label
    if out_dir.exists():
        shutil.rmtree(out_dir)
    refs_dir.mkdir(parents=True)
    scraped_dir.mkdir(parents=True)

    master = random.Random(seed)
    ground_truth: dict[str, Any] = {}
    manifest: dict[str, Any] = {}
    products_meta: dict[str, Any] = {}

    for idx in range(n_products):
        sku = f"SKU{idx + 1:03d}"
        rng = random.Random(f"{seed}:{sku}")
        state = make_state(sku, rng, index=idx)

        n_versions = rng.randint(2, 4)
        states = [state]
        transitions: dict[str, list[dict]] = {}
        labels = ["v1"]

        for v in range(1, n_versions):
            nxt, records = build_transition(states[-1], rng)
            label = f"v{v + 1}"
            transitions[f"{labels[-1]}->{label}"] = records
            labels.append(label)
            states.append(nxt)

        sku_ref_dir = refs_dir / sku
        sku_ref_dir.mkdir(parents=True)
        version_files = {}
        for label, st in zip(labels, states):
            img = render(st)
            p = sku_ref_dir / f"{label}.png"
            img.save(p, "PNG", optimize=False)
            version_files[label] = str(p.relative_to(out_dir))

        # Approval dates walk backwards from the newest version.
        approved = {}
        base_year, base_month = 2026, 3
        for i, label in enumerate(labels):
            month = base_month - (len(labels) - 1 - i) * 4
            year = base_year
            while month <= 0:
                month += 12
                year -= 1
            approved[label] = f"{year}-{month:02d}-14T00:00:00+00:00"

        ground_truth[sku] = {
            "versions": labels,
            "current": labels[-1],
            "files": version_files,
            "approved_at": approved,
            "transitions": transitions,
        }
        products_meta[sku] = {
            "name": f"{state.name} — {state.variant}",
            "brand": state.brand,
        }

        # --- marketplace variants ------------------------------------------
        combos = full_cross_product() if full else variant_combinations(
            variants_per_version, seed=seed * 7919 + idx
        )
        for label, st in zip(labels, states):
            ref_img = Image.open(sku_ref_dir / f"{label}.png").convert("RGB")

            # Byte-identical copy — exercises the hash fast path.
            untouched = scraped_dir / f"{sku}__{label}__untouched.png"
            shutil.copyfile(sku_ref_dir / f"{label}.png", untouched)
            manifest[untouched.name] = {
                "product_id": sku, "true_version": label, "quality": None,
                "size": [CANVAS, CANVAS], "padding": None, "format": "png",
                "extra": "byte_identical", "untouched": True,
            }

            for c in combos:
                fname = variant_filename(sku, label, c)
                emit_variant(ref_img, scraped_dir / fname, c)
                manifest[fname] = {
                    "product_id": sku, "true_version": label,
                    "quality": c["quality"], "size": list(c["size"]),
                    "padding": c["padding"], "format": c["format"],
                    "extra": c["extra"], "untouched": False,
                }

        if (idx + 1) % 5 == 0 or idx + 1 == n_products:
            print(f"  generated {idx + 1}/{n_products} products", flush=True)

    # The scraper's output contract: which product a listing image belongs to, and
    # nothing else. The pipeline reads only this — never the version encoded in the
    # filename, which exists solely for the test harness to check answers against.
    scrape_manifest = {name: {"product_id": meta["product_id"]}
                       for name, meta in manifest.items()}
    (scraped_dir / "scrape_manifest.json").write_text(json.dumps(scrape_manifest, indent=2))

    (out_dir / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2))
    (out_dir / "variants_manifest.json").write_text(json.dumps(manifest, indent=2))
    (out_dir / "products.json").write_text(json.dumps(products_meta, indent=2))

    summary = {
        "products": n_products,
        "versions": sum(len(g["versions"]) for g in ground_truth.values()),
        "scraped_images": len(manifest),
        "seed": seed,
        "run_label": run_label,
    }
    (out_dir / "corpus_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.corpus")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate a synthetic corpus")
    g.add_argument("--products", type=int, default=50)
    g.add_argument("--out", default="./data/corpus")
    g.add_argument("--seed", type=int, default=20260101)
    g.add_argument("--variants-per-version", type=int, default=16,
                   help="stratified sample size from the transformation cross-product")
    g.add_argument("--full-cross-product", action="store_true",
                   help="emit all 288 transformations per version (slow)")
    g.add_argument("--run-label", default="run_2026_01")

    args = ap.parse_args(argv)
    if args.cmd == "generate":
        summary = generate(Path(args.out), args.products, args.seed,
                           args.variants_per_version, args.full_cross_product,
                           args.run_label)
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
