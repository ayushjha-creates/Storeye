"""Unit tests for the conservative OCR-text -> product name matcher.

No database: the matcher is pure and deterministic. It must resolve printed
package names to catalog products when they clearly agree, and must NEVER match
label noise (dates, MRP, EXP/MFG/BATCH) or unrelated text.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.product.name_matcher import (
    DEFAULT_MIN_SCORE,
    ProductNameMatcher,
    normalize_name,
)

pytestmark = pytest.mark.no_db


def _product(product_id, name, *, brand=None, ai_classes=None, price="10.00"):
    return SimpleNamespace(
        id=product_id,
        name=name,
        brand=brand,
        ai_classes=ai_classes,
        selling_price=price,
    )


def _matcher():
    return ProductNameMatcher.from_products(
        [
            _product("p1", "Amul Taaza Milk", brand="Amul"),
            _product("p2", "Glucon-D", ai_classes=["Glucon-D Orange"]),
        ]
    )


def test_normalize_folds_case_and_punctuation():
    assert normalize_name("  Glucon-D  ORANGE ") == "glucon d orange"


def test_exact_name_match():
    match = _matcher().match_lines(["Amul Taaza Milk"])
    assert match is not None
    assert match.product_id == "p1"
    assert match.score == 1.0


def test_containment_match_on_package_line():
    match = _matcher().match_lines(["AMUL TAAZA MILK 1L PACK"])
    assert match is not None
    assert match.product_id == "p1"
    assert match.score >= DEFAULT_MIN_SCORE


def test_brand_alias_match():
    match = _matcher().match_lines(["AMUL"])
    assert match is not None
    assert match.product_id == "p1"


def test_ai_class_alias_match():
    match = _matcher().match_lines(["Glucon-D Orange"])
    assert match is not None
    assert match.product_id == "p2"


def test_label_noise_is_never_matched():
    matcher = _matcher()
    for noise in ["EXP 12/09/2027", "MFG 01/2026", "MRP 50.00", "BATCH AB123", "12 09 2027"]:
        assert matcher.match_lines([noise]) is None


def test_unrelated_text_is_not_forced_into_a_match():
    assert _matcher().match_lines(["SOME UNRELATED PACKAGE"]) is None
    assert _matcher().match_lines([]) is None


def test_deterministic_tie_break_by_name_then_id():
    matcher = ProductNameMatcher.from_products(
        [
            _product("zzz", "Same Name"),
            _product("aaa", "Same Name"),
        ]
    )
    first = matcher.match_lines(["Same Name"])
    second = matcher.match_lines(["Same Name"])
    assert first is not None and second is not None
    assert first.product_id == second.product_id == "aaa"


def test_no_products_means_no_match():
    assert ProductNameMatcher.from_products([]).match_lines(["Amul Taaza Milk"]) is None
