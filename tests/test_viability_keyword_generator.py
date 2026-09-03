from __future__ import annotations

import pytest

from db_collector_os.viability.keyword_generator import generate_candidates


def test_main_keyword_always_included_and_tagged():
    specs = generate_candidates(["アクセサリー オーダーメイド"])
    assert len(specs) == 1
    assert specs[0].keyword == "アクセサリー オーダーメイド"
    assert specs[0].is_main is True
    assert specs[0].axis == {}


def test_axis_values_generate_both_orders_and_are_tagged():
    specs = generate_candidates(
        ["アクセサリー オーダーメイド"],
        axes={"region": ["東京"], "motif": ["スカル"]},
    )
    keywords = {s.keyword: s for s in specs}
    assert "東京 アクセサリー オーダーメイド" in keywords
    assert "アクセサリー オーダーメイド 東京" in keywords
    assert keywords["東京 アクセサリー オーダーメイド"].axis == {"region": "東京"}
    assert keywords["東京 アクセサリー オーダーメイド"].is_main is False
    assert "スカル アクセサリー オーダーメイド" in keywords


def test_combos_are_space_joined_and_tagged():
    specs = generate_candidates(
        ["アクセサリー オーダーメイド"], combos=[["シルバーアクセサリー", "工房", "東京"]]
    )
    combo = [s for s in specs if s.keyword == "シルバーアクセサリー 工房 東京"]
    assert len(combo) == 1
    assert combo[0].axis == {"combo": "シルバーアクセサリー / 工房 / 東京"}


def test_duplicate_keywords_are_deduplicated_preserving_first_seen():
    specs = generate_candidates(
        ["アクセサリー オーダーメイド"],
        axes={"region": ["東京"], "target": ["東京"]},  # same value under two axes
    )
    keywords = [s.keyword for s in specs]
    assert keywords.count("東京 アクセサリー オーダーメイド") == 1


def test_unknown_axis_name_raises():
    with pytest.raises(ValueError):
        generate_candidates(["x"], axes={"not_a_real_axis": ["y"]})


def test_theme_with_no_axes_at_all_still_returns_main_only():
    specs = generate_candidates(["ソロテーマ"])
    assert [s.keyword for s in specs] == ["ソロテーマ"]
