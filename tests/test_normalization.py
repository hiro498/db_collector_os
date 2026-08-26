from __future__ import annotations

from db_collector_os.normalization import (
    normalize_address,
    normalize_name,
    normalize_telephone,
    normalize_unicode,
    normalize_url,
    normalize_whitespace,
)


def test_normalize_whitespace_collapses_and_strips():
    assert normalize_whitespace("  a   b\n\tc  ") == "a b c"
    assert normalize_whitespace(None) == ""


def test_normalize_unicode_folds_fullwidth():
    assert normalize_unicode("ＡＢＣ１２３") == "ABC123"


def test_normalize_url_strips_tracking_params_and_fragment():
    a = normalize_url("HTTPS://Example.com/Path/?utm_source=x&b=2&a=1#frag")
    b = normalize_url("https://example.com/Path?a=1&b=2")
    assert a == b


def test_normalize_url_strips_trailing_slash():
    assert normalize_url("https://example.com/a/") == normalize_url("https://example.com/a")


def test_normalize_telephone_domestic_to_e164_style():
    assert normalize_telephone("03-1234-5678") == "+81312345678"


def test_normalize_telephone_already_international():
    assert normalize_telephone("+81 3 1234 5678") == "+81312345678"


def test_normalize_telephone_empty():
    assert normalize_telephone(None) == ""
    assert normalize_telephone("") == ""


def test_normalize_address_folds_hyphen_variants():
    a = normalize_address("東京都渋谷区神宮前1‐2‐3")
    b = normalize_address("東京都渋谷区神宮前1-2-3")
    assert a == b


def test_normalize_name_strips_corporate_suffix_and_punctuation():
    a = normalize_name("株式会社Acme Tires")
    b = normalize_name("Acme Tires Inc.")
    assert a == "acmetires"
    assert b == "acmetires"
    assert a == b
