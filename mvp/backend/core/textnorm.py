"""Text normalization, tokenization and typed difference classification.

Kept out of the stage so it is a pure function of two strings and can be tested
without an image, an OCR engine or a database. The stage above it does nothing but
call `compare_text` and write down what it said.

The governing rule: **classify by type, never by string equality.** `"450"` and
`"450.0"` are the same number and must not fire. `"450mg"` and `"480mg"` are
different numbers and must. `"450mg"` and `"45Omg"` differ by one confusable
character and are almost certainly one OCR misread of the same value, so they go
to `UNCERTAIN` rather than to either confident answer.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

from .types import (
    CONFUSABLE_CHARACTERS,
    COSMETIC,
    MATERIAL,
    NO_DIFFERENCE,
    NONE,
    NUMBER_AND_UNIT_CHANGED,
    NUMBER_CHANGED,
    NUMBER_FORMAT,
    PUNCTUATION_ONLY,
    TEXT_ADDED,
    TEXT_CHANGED,
    TEXT_REMOVED,
    UNCERTAIN,
)

# Unit spellings that mean the same thing. Marketplaces, and OCR, are both
# inconsistent about these, and neither inconsistency is a change to the pack.
UNIT_ALIASES = {
    "gm": "g", "gms": "g", "gram": "g", "grams": "g", "grm": "g",
    "mgs": "mg", "milligram": "mg", "milligrams": "mg",
    "kcals": "kcal", "calorie": "kcal", "calories": "kcal", "cal": "kcal",
    "kj": "kj", "kilojoule": "kj", "kilojoules": "kj",
    "ml": "ml", "millilitre": "ml", "millilitres": "ml", "milliliter": "ml",
    "ltr": "l", "litre": "l", "litres": "l", "liter": "l",
    "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
    "mcg": "ug", "µg": "ug", "microgram": "ug", "micrograms": "ug",
    "percent": "%", "pct": "%",
}

KNOWN_UNITS = {"g", "mg", "kg", "ug", "kcal", "kj", "ml", "l", "%", "iu", "oz", "lb"}

# Character pairs OCR genuinely confuses. Not a general typo model: these are the
# specific substitutions a recognizer makes on packaging type, and treating any
# other single-character edit as "probably OCR" would silently swallow real edits
# like 3 -> 8.
# Stored upper-cased and looked up upper-cased, because `normalize` case-folds
# and `0`/`O` is precisely the pair that matters.
CONFUSABLE_PAIRS = {
    frozenset("0O"), frozenset("0Q"), frozenset("0D"),
    frozenset("1L"), frozenset("1I"), frozenset("LI"),
    frozenset("5S"), frozenset("8B"), frozenset("2Z"), frozenset("6G"),
    frozenset("9G"), frozenset("UV"),
}
# Multi-character confusions, handled before the single-character test.
CONFUSABLE_SEQUENCES = [("rn", "m"), ("cl", "d"), ("vv", "w"), ("ii", "u")]

# A leading bare decimal point is a real packaging convention: `.5 g`.
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)$")
_NUMBER_UNIT_RE = re.compile(
    r"^([+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+))\s*([a-zµ%]+)$", re.IGNORECASE)
_PUNCT_ONLY_RE = re.compile(r"^[^\w]+$", re.UNICODE)


def normalize(text: str) -> str:
    """NFKC, collapse whitespace, case-fold, unify units and number formats.

    Order matters. NFKC first, because it is what turns a full-width digit or a
    ligature into the plain character everything else is written against.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = s.replace("–", "-").replace("—", "-").replace("−", "-")
    s = s.replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip().casefold()
    tokens = [_normalize_token(tok) for tok in s.split(" ") if tok]
    return " ".join(_join_units(tokens))


def _join_units(tokens: list[str]) -> list[str]:
    """Merge a bare number with a unit that follows it as a separate token.

    `450 mg` and `450mg` are the same value, and which of the two an OCR engine
    returns depends on the kerning of the crop it was handed. Without this the
    two compare as a token-count mismatch and a value that never changed reads
    as a material difference.
    """
    out: list[str] = []
    i = 0
    while i < len(tokens):
        current = tokens[i]
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        if (following in KNOWN_UNITS and _NUMBER_RE.match(current)):
            out.append(f"{current}{following}")
            i += 2
            continue
        out.append(current)
        i += 1
    return out


_TRAILING_PUNCT = ".,;:!?()[]{}\"'"


def _normalize_token(tok: str) -> str:
    stripped = tok.rstrip(_TRAILING_PUNCT)
    # A leading `.` or `,` is punctuation everywhere except in front of a digit,
    # where it is a bare decimal point: `.5 g` is a real packaging convention and
    # stripping it turns half a gram into five.
    if not re.match(r"^[.,]\d", stripped):
        stripped = stripped.lstrip(_TRAILING_PUNCT)
    if not stripped:
        return tok

    m = _NUMBER_UNIT_RE.match(stripped)
    if m:
        value, unit = m.group(1), m.group(2)
        return f"{_normalize_number(value)}{UNIT_ALIASES.get(unit, unit)}"

    if _NUMBER_RE.match(stripped):
        return _normalize_number(stripped)

    return UNIT_ALIASES.get(stripped, stripped)


def _normalize_number(s: str) -> str:
    """`0.5`, `.5` and `0,5` are one value written three ways.

    A comma is treated as a decimal separator only when it is followed by one to
    three digits and the string has no other separator — otherwise `1,250` (a
    thousands separator) would become `1.25`.
    """
    t = s.strip()
    if "," in t and "." not in t:
        head, _, tail = t.partition(",")
        t = f"{head}.{tail}" if 1 <= len(tail) <= 2 else head + tail
    if t.startswith(".") or t.startswith(","):
        t = "0" + t.replace(",", ".", 1)
    try:
        v = float(t)
    except ValueError:
        return s
    # Render through a canonical form so 450, 450.0 and 4.5e2 agree.
    if v == int(v):
        return str(int(v))
    return f"{v:g}"


def parse_number(tok: str) -> tuple[float, str] | None:
    """`("480", "mg")` -> `(480.0, "mg")`. Returns None if it is not a number."""
    t = tok.strip()
    m = _NUMBER_UNIT_RE.match(t)
    if m:
        try:
            return float(_normalize_number(m.group(1))), UNIT_ALIASES.get(
                m.group(2).casefold(), m.group(2).casefold())
        except ValueError:
            return None
    if _NUMBER_RE.match(t):
        try:
            return float(_normalize_number(t)), ""
        except ValueError:
            return None
    return None


def tokenize(text: str) -> list[str]:
    return [t for t in normalize(text).split(" ") if t]


# --------------------------------------------------------------------------
# Confusables
# --------------------------------------------------------------------------


def edit_distance(a: str, b: str, cap: int = 4) -> int:
    """Levenshtein, bailing out once it exceeds `cap`."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def is_confusable(a: str, b: str, max_distance: int = 1) -> bool:
    """Whether two tokens differ only in ways OCR routinely gets wrong.

    Checked case-insensitively against the original strings rather than the
    normalized ones, because normalization case-folds and `0`/`O` is exactly the
    pair that matters.
    """
    if a == b:
        return False

    for x, y in CONFUSABLE_SEQUENCES:
        if a.replace(x, y) == b.replace(x, y):
            return True

    if len(a) != len(b):
        # A pure insertion or deletion is not a confusable substitution, with the
        # exception of the multi-character sequences handled above.
        return edit_distance(a, b, cap=max_distance) <= max_distance and _all_confusable_padded(a, b)

    diffs = [(ca, cb) for ca, cb in zip(a, b) if ca != cb]
    if not diffs or len(diffs) > max_distance:
        return False
    return all(frozenset((ca.upper(), cb.upper())) in CONFUSABLE_PAIRS
               for ca, cb in diffs)


def _all_confusable_padded(a: str, b: str) -> bool:
    """Length-differing pairs are only confusable via the sequence table."""
    return any(a.replace(x, y) == b.replace(x, y) for x, y in CONFUSABLE_SEQUENCES)


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


@dataclass
class TextDifference:
    """One classified difference between two readings of the same region."""

    difference_type: str
    severity: str
    reference: str
    marketplace: str
    detail: str


@dataclass
class TextComparison:
    difference_type: str
    severity: str
    detail: str
    differences: list[TextDifference]
    # Word-level opcodes for the UI's diff view: (tag, ref_tokens, mkt_tokens).
    opcodes: list[tuple[str, list[str], list[str]]]


def compare_text(reference: str, marketplace: str, *,
                 numeric_relative_tolerance: float = 1e-9,
                 confusable_max_distance: int = 1) -> TextComparison:
    """Token-align two readings and classify every difference by type."""
    ref_tokens = tokenize(reference)
    mkt_tokens = tokenize(marketplace)

    opcodes: list[tuple[str, list[str], list[str]]] = []
    differences: list[TextDifference] = []

    # Where the reader split words is not information about the pack. A crop read
    # as "added sugar" on one side and "added suga ar" on the other contains the
    # same characters in the same order — the recognizer put a token boundary in
    # a different place, which is an artefact of the reader, not a change to the
    # artwork. Measured: this alone accounted for a false material finding on a
    # glare-damaged photograph.
    if ref_tokens and "".join(ref_tokens) == "".join(mkt_tokens):
        return TextComparison(
            difference_type=NO_DIFFERENCE, severity=NONE,
            detail="The same text, with the reader splitting the words differently.",
            differences=[],
            opcodes=[("equal", ref_tokens, mkt_tokens)])

    sm = difflib.SequenceMatcher(a=ref_tokens, b=mkt_tokens, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        a = ref_tokens[i1:i2]
        b = mkt_tokens[j1:j2]
        opcodes.append((tag, a, b))
        if tag == "equal":
            continue
        if tag == "replace":
            differences.extend(_classify_replace(
                a, b, reference, marketplace,
                numeric_relative_tolerance, confusable_max_distance))
        elif tag == "delete":
            differences.append(_classify_absent(a, removed=True))
        elif tag == "insert":
            differences.append(_classify_absent(b, removed=False))

    if not differences:
        return TextComparison(
            difference_type=NO_DIFFERENCE, severity=NONE,
            detail=("The text reads the same on both sides."
                    if ref_tokens or mkt_tokens
                    else "No text was read on either side."),
            differences=[], opcodes=opcodes)

    # The region takes its worst constituent difference. A region containing one
    # material change and four cosmetic ones is a material change.
    worst = max(differences, key=lambda d: _RANK[d.severity])
    return TextComparison(
        difference_type=worst.difference_type, severity=worst.severity,
        detail=worst.detail, differences=differences, opcodes=opcodes)


_RANK = {MATERIAL: 3, UNCERTAIN: 2, COSMETIC: 1, NONE: 0}


def _classify_replace(a: list[str], b: list[str], raw_ref: str, raw_mkt: str,
                      rel_tol: float, confusable_max: int) -> list[TextDifference]:
    """Classify a replaced run of tokens, pairing them up where lengths allow."""
    out: list[TextDifference] = []

    if len(a) == len(b):
        pairs = list(zip(a, b))
    else:
        # Unequal runs cannot be paired token for token without inventing an
        # alignment. Compare them as two phrases instead.
        pairs = [(" ".join(a), " ".join(b))]

    for ta, tb in pairs:
        out.append(_classify_pair(ta, tb, raw_ref, raw_mkt, rel_tol, confusable_max))
    return out


def _classify_pair(ta: str, tb: str, raw_ref: str, raw_mkt: str,
                   rel_tol: float, confusable_max: int) -> TextDifference:
    if ta == tb:
        return TextDifference(NO_DIFFERENCE, NONE, ta, tb, "Identical after normalizing.")

    # Same characters, different token boundaries — see `compare_text`. Applies
    # again here because a phrase-versus-phrase comparison can contain a local
    # split that the whole-string check did not.
    flat_a, flat_b = ta.replace(" ", ""), tb.replace(" ", "")
    if flat_a == flat_b:
        return TextDifference(
            NO_DIFFERENCE, NONE, ta, tb,
            "The same characters, split into words differently by the reader.")

    # Checked **before** the number branch, and the order is load-bearing.
    # `45O` parses as the number 45 carrying a unit called "o", so a numeric
    # comparison would report `450mg` against `45O` as both the value and the
    # unit having changed — a confident material finding built entirely on a
    # misread character. A real digit change such as 450 to 480 is not
    # confusable, so it still reaches the numeric branch below.
    if is_confusable(ta, tb, confusable_max):
        return TextDifference(
            CONFUSABLE_CHARACTERS, UNCERTAIN, ta, tb,
            f"'{ta}' and '{tb}' differ by one character that this kind of reader "
            f"routinely confuses, so this may be a misreading rather than a change.")

    na, nb = parse_number(ta), parse_number(tb)

    if na is not None and nb is not None:
        (va, ua), (vb, ub) = na, nb
        same_value = abs(va - vb) <= rel_tol * max(abs(va), abs(vb), 1.0)
        if same_value and ua == ub:
            return TextDifference(
                NUMBER_FORMAT, COSMETIC, ta, tb,
                f"Same value written differently: {ta} and {tb} are both {va:g}.")
        if same_value and ua != ub:
            return TextDifference(
                NUMBER_AND_UNIT_CHANGED, MATERIAL, ta, tb,
                f"The number is the same but the unit changed, from {ua or 'none'} "
                f"to {ub or 'none'} — which changes what the value means.")
        if ua != ub:
            return TextDifference(
                NUMBER_AND_UNIT_CHANGED, MATERIAL, ta, tb,
                f"Both the number and its unit changed, from {ta} to {tb}.")
        # A number changed by exactly one confusable digit is more likely a
        # misread than an edit, and the corpus cannot tell them apart either.
        if is_confusable(ta, tb, confusable_max):
            return TextDifference(
                CONFUSABLE_CHARACTERS, UNCERTAIN, ta, tb,
                f"{ta} and {tb} differ by one character that this kind of reader "
                f"routinely confuses, so this may be a misreading rather than a "
                f"change.")
        return TextDifference(
            NUMBER_CHANGED, MATERIAL, ta, tb,
            f"The value changed from {va:g} to {vb:g}"
            + (f" {ua}." if ua else "."))

    if _PUNCT_ONLY_RE.match(ta) and _PUNCT_ONLY_RE.match(tb):
        return TextDifference(
            PUNCTUATION_ONLY, COSMETIC, ta, tb,
            "Only punctuation differs.")

    if is_confusable(ta, tb, confusable_max) or is_confusable(flat_a, flat_b,
                                                              confusable_max):
        return TextDifference(
            CONFUSABLE_CHARACTERS, UNCERTAIN, ta, tb,
            f"'{ta}' and '{tb}' differ by one character that this kind of reader "
            f"routinely confuses, so this may be a misreading rather than a change.")

    # A repeated or dropped character in an otherwise identical phrase is the
    # signature of a recognizer stuttering across a damaged crop, not of an edit.
    if _is_repetition(flat_a, flat_b):
        return TextDifference(
            CONFUSABLE_CHARACTERS, UNCERTAIN, ta, tb,
            f"'{ta}' and '{tb}' are the same words with a character repeated or "
            f"dropped, which is what this kind of reader does on a damaged image.")

    return TextDifference(
        TEXT_CHANGED, MATERIAL, ta, tb,
        f"The wording changed from '{ta}' to '{tb}'.")


def _is_repetition(a: str, b: str) -> bool:
    """Whether one string is the other with a character doubled or dropped.

    Deliberately narrow: only a *repeat* of an adjacent character counts. A
    genuine insertion of a different character — `450` to `4500` — is not a
    repetition and stays material.
    """
    if abs(len(a) - len(b)) != 1:
        return False
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    for i in range(len(longer)):
        if longer[:i] + longer[i + 1:] != shorter:
            continue
        # The removed character must duplicate one of its neighbours.
        prev = longer[i - 1] if i > 0 else None
        nxt = longer[i + 1] if i + 1 < len(longer) else None
        if longer[i] in (prev, nxt):
            return True
    return False


def _classify_absent(tokens: list[str], removed: bool) -> TextDifference:
    phrase = " ".join(tokens)
    if all(_PUNCT_ONLY_RE.match(t) for t in tokens):
        return TextDifference(
            PUNCTUATION_ONLY, COSMETIC,
            phrase if removed else "", "" if removed else phrase,
            "Only punctuation was added or removed.")
    if removed:
        return TextDifference(
            TEXT_REMOVED, MATERIAL, phrase, "",
            f"'{phrase}' is on the reference but not on the marketplace image.")
    return TextDifference(
        TEXT_ADDED, MATERIAL, "", phrase,
        f"'{phrase}' is on the marketplace image but not on the reference.")
