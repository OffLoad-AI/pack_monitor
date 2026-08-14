"""Text normalization and difference classification.

Pure functions over two strings, so these run in milliseconds and cover the
classification table exhaustively — which the end-to-end tests cannot, because
they can only exercise whatever the corpus happens to generate.
"""

from __future__ import annotations

import pytest

from core.textnorm import compare_text, is_confusable, normalize, parse_number, tokenize


class TestNormalize:
    @pytest.mark.parametrize("raw,expected", [
        ("450 mg", "450mg"),
        ("450mg", "450mg"),
        ("450 MG", "450mg"),
        ("450 gm", "450g"),
        ("450 grams", "450g"),
        ("12 Kcal", "12kcal"),
        ("12 calories", "12kcal"),
        ("  spaced   out  ", "spaced out"),
    ])
    def test_units_unify(self, raw, expected):
        assert normalize(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("450", "450"),
        ("450.0", "450"),
        ("0.5", "0.5"),
        (".5", "0.5"),
        ("0,5", "0.5"),
    ])
    def test_number_formats_unify(self, raw, expected):
        assert normalize(raw) == expected

    def test_thousands_separator_is_not_a_decimal_point(self):
        """`1,250` is one thousand two hundred and fifty, not 1.25."""
        assert normalize("1,250") == "1250"

    def test_nfkc(self):
        assert normalize("４５０ｍｇ") == "450mg"

    def test_empty(self):
        assert normalize("") == ""
        assert tokenize("") == []


class TestParseNumber:
    def test_with_unit(self):
        assert parse_number("480mg") == (480.0, "mg")

    def test_bare(self):
        assert parse_number("480") == (480.0, "")

    def test_not_a_number(self):
        assert parse_number("protein") is None


class TestConfusables:
    @pytest.mark.parametrize("a,b", [("450", "45O"), ("1l", "11"), ("5S", "55")])
    def test_confusable_pairs(self, a, b):
        assert is_confusable(a, b)

    def test_rn_m_sequence(self):
        assert is_confusable("rnodern", "modern")

    @pytest.mark.parametrize("a,b", [("450", "480"), ("380", "480")])
    def test_real_digit_changes_are_not_confusable(self, a, b):
        """`3` to `8` is a real edit. Treating any single-character difference as
        OCR noise would swallow exactly the drift this tool exists to catch."""
        assert not is_confusable(a, b)


class TestClassification:
    def test_number_changed_is_material(self):
        r = compare_text("sodium 450 mg", "sodium 480 mg")
        assert r.severity == "MATERIAL"
        assert r.difference_type == "NUMBER_CHANGED"

    def test_same_value_different_format_is_cosmetic(self):
        """`450` and `450.0` must not fire."""
        r = compare_text("sodium 450 mg", "sodium 450.0 mg")
        assert r.severity == "NONE"
        assert r.difference_type == "NO_DIFFERENCE"

    def test_unit_variants_do_not_fire(self):
        r = compare_text("protein 12 g", "protein 12 gm")
        assert r.severity == "NONE"

    def test_unit_changed_is_material(self):
        r = compare_text("sodium 450 mg", "sodium 450 g")
        assert r.severity == "MATERIAL"
        assert r.difference_type == "NUMBER_AND_UNIT_CHANGED"

    def test_number_and_unit_both_changed_is_material(self):
        r = compare_text("sodium 450 mg", "sodium 480 g")
        assert r.severity == "MATERIAL"

    def test_confusable_number_is_uncertain(self):
        """A digit differing by a character the reader confuses is not evidence."""
        r = compare_text("sodium 450 mg", "sodium 45O mg")
        assert r.severity == "UNCERTAIN"
        assert r.difference_type == "CONFUSABLE_CHARACTERS"

    def test_word_removed_is_material(self):
        r = compare_text("no added sugar", "no sugar")
        assert r.severity == "MATERIAL"
        assert r.difference_type == "TEXT_REMOVED"

    def test_word_added_is_material(self):
        r = compare_text("no sugar", "no added sugar")
        assert r.severity == "MATERIAL"
        assert r.difference_type == "TEXT_ADDED"

    def test_punctuation_only_is_cosmetic(self):
        r = compare_text("high protein , vegan", "high protein . vegan")
        assert r.severity in ("COSMETIC", "NONE")

    def test_identical_text_is_no_difference(self):
        r = compare_text("high protein", "High  Protein")
        assert r.severity == "NONE"
        assert r.difference_type == "NO_DIFFERENCE"

    def test_token_split_differences_are_not_a_change(self):
        """Where the reader put a word break is not information about the pack."""
        r = compare_text("added sugar", "added suga r")
        assert r.severity == "NONE"
        assert r.difference_type == "NO_DIFFERENCE"

    def test_repeated_character_is_uncertain_not_material(self):
        """A stuttered character is what a recognizer does on a damaged crop."""
        r = compare_text("coffee cocoa", "coffee cocooa")
        assert r.severity == "UNCERTAIN"

    def test_both_empty(self):
        r = compare_text("", "")
        assert r.severity == "NONE"

    def test_opcodes_are_produced_for_the_ui(self):
        r = compare_text("sodium 450 mg", "sodium 480 mg")
        assert r.opcodes
        assert any(tag != "equal" for tag, _a, _b in r.opcodes)
