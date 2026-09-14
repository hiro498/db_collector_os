"""Proprietary / primary information detection (spec section 4 -- explicitly
the most important part of this phase). Detects language that signals
firsthand experience, a named methodology, or proprietary/derived data,
as opposed to a page merely re-summarizing information that already
exists elsewhere. Presence of these phrases is evidence, not proof --
every match is stored with its surrounding text (see pipeline.py) rather
than only a final score, per spec section 15.
"""

from __future__ import annotations

import re

_FIRSTHAND_PATTERNS = (
    "実際に", "編集部が", "編集部で", "取材し", "体験し", "試した結果", "使ってみた",
    "覆面調査", "実測", "検証した結果", "実食", "自分の目で", "現地を訪れ", "実際の利用者",
)
_METHODOLOGY_PATTERNS = (
    "調査方法", "集計方法", "算出方法", "調査対象", "調査期間", "調査日", "集計日",
    "アンケート", "評価基準", "選定基準", "評価方法",
)
_PROPRIETARY_DATA_PATTERNS = (
    "自社調査", "独自調査", "独自集計", "自社データ", "独自データ", "独自ランキング",
    "独自比較", "自社アンケート", "編集部調べ",
)
_PRIMARY_SOURCE_PATTERNS = (
    "公式発表によると", "公式によると", "本人が", "本人へのインタビュー", "一次情報",
    "インタビューで語った", "公式サイトによると", "運営元によると",
)
_PROPRIETARY_METRIC_PATTERNS = (
    "独自指数", "独自スコア", "独自レーティング", "オリジナル評価", "自社レーティング", "独自偏差値",
)


def _count_matches(text: str, patterns: tuple[str, ...]) -> list[tuple[str, str]]:
    """Returns [(matched_pattern, context_snippet), ...]."""
    hits = []
    for pattern in patterns:
        for m in re.finditer(re.escape(pattern), text):
            hits.append((pattern, text[max(0, m.start() - 20): m.end() + 30]))
    return hits


def detect_proprietary_signals(text: str) -> dict[str, object]:
    if not text:
        return {
            "firsthand_hits": [], "methodology_hits": [], "proprietary_data_hits": [],
            "primary_source_hits": [], "proprietary_metric_hits": [],
        }
    return {
        "firsthand_hits": _count_matches(text, _FIRSTHAND_PATTERNS),
        "methodology_hits": _count_matches(text, _METHODOLOGY_PATTERNS),
        "proprietary_data_hits": _count_matches(text, _PROPRIETARY_DATA_PATTERNS),
        "primary_source_hits": _count_matches(text, _PRIMARY_SOURCE_PATTERNS),
        "proprietary_metric_hits": _count_matches(text, _PROPRIETARY_METRIC_PATTERNS),
    }


def source_traceability_score(primary_source_count: int, methodology_count: int) -> int:
    """0-100: can a reader tell *where* a claim/number on this page came
    from? Purely a function of explicit sourcing/methodology language,
    never of numeric density."""
    return max(0, min(100, primary_source_count * 25 + methodology_count * 20))


def proprietary_information_score(
    firsthand_count: int, methodology_count: int, proprietary_data_count: int,
    primary_source_count: int, proprietary_metric_count: int, verifiable_fact_count: int,
) -> int:
    """0-100. A page that only restates numbers found elsewhere (no
    firsthand/methodology/proprietary-data language at all) scores 0 here
    regardless of how many numbers it contains -- see numeric_facts.py's
    quality_score for the separate, numeric-specific component.
    """
    raw = (
        firsthand_count * 15 + methodology_count * 12 + proprietary_data_count * 20
        + primary_source_count * 10 + proprietary_metric_count * 15
        + min(verifiable_fact_count, 5) * 4
    )
    return max(0, min(100, raw))
