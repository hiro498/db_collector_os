"""Configurable thresholds for the PHASE 15 Production Validation layer.
Every threshold that shapes a decision lives here, not inline -- and every
one of them thresholds an *existing* PHASE 1/12/13/14 signal; this module
computes no new score of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# spec section 6: production-validation safety default -- explicit
# override required to go beyond this, never silently expanded.
DEFAULT_MAX_PAGES = 30
DEFAULT_RATE_LIMIT_REQUESTS_PER_SECOND = 1.0

# spec section 10: KPI thresholds over the human-audited (or, absent that,
# auto-quality-proxy) TOP50 A+B rate.
TOP50_AB_PASS_THRESHOLD = 0.80
TOP50_AB_TARGET_THRESHOLD = 0.90
TOP_N_FOR_KPI = 50
TOP_N_CANDIDATES = 100

# spec section 13: money_keyword_class thresholds on the *existing*
# PHASE 1 commercial_score (0-100) -- no new commercial model.
MONEY_KEYWORD_HIGH_THRESHOLD = 60
MONEY_KEYWORD_MEDIUM_THRESHOLD = 30

# spec section 9: keyword-cluster similarity threshold (Jaccard over
# tokenized surface forms). Deliberately conservative -- clustering never
# merges scores/counts, only labels likely-related candidates for human
# review, and Japanese word order is never stripped to force a match.
CLUSTER_JACCARD_THRESHOLD = 0.8

# spec section 20: blue-ocean candidate heuristic thresholds, all against
# already-computed PHASE 14 fields.
BLUE_OCEAN_MIN_OPPORTUNITY_SCORE = 65.0
BLUE_OCEAN_MIN_COMMERCIAL_SCORE = 30.0
BLUE_OCEAN_MIN_CONTENT_GAP_SCORE = 40.0
BLUE_OCEAN_MAX_COMPETITOR_PROPRIETARY_SCORE = 40.0

# spec section 11: noise-audit surface-text patterns, checked against a
# keyword's own text (not a re-implementation of the boilerplate detector
# -- this only flags candidates whose *text itself* names a boilerplate
# section, on top of whatever `is_boilerplate` already excluded upstream).
NOISE_TEXT_PATTERNS: tuple[str, ...] = (
    "利用規約", "お問い合わせ", "問い合わせ", "ログイン", "会員登録", "会社概要", "運営会社",
    "プライバシー", "個人情報", "copyright", "サイトマップ", "メニュー", "footer", "navigation",
    "広告表記", "アフィリエイト表記", "cookie", "クッキー", "フォロー", "シェア", "関連記事",
    "新着記事", "人気記事", "topへ戻る", "ページトップ",
)
NOISE_MIN_TEXT_LENGTH = 2  # a bare 1-character candidate is noise regardless of score

# spec section 11's "意味の薄い1語" (thin single words): bare site-scaffolding
# vocabulary (category/tag/list/article/site labels) that is only noise
# when it IS the entire keyword -- "サイト" alone is scaffolding, but
# "比較サイト" ("comparison site") is a legitimate compound keyword, so
# these check for an exact match, never a substring match.
NOISE_EXACT_TERMS: tuple[str, ...] = (
    "サイト", "タグ", "カテゴリー", "カテゴリ", "一覧", "記事", "ホーム", "トップページ", "ページ",
)


@dataclass(frozen=True)
class PriorityTieBreak:
    """spec section 19: sort order for the Target Keyword ranking. Primary
    key is always overall_opportunity_score DESC; ties fall through this
    list in order. No new combined score is computed from these -- they
    are used purely as a Python sort key tuple."""

    fields: tuple[str, ...] = ("commercial_score", "confidence_value", "best_keyword_score")
    directions: tuple[str, ...] = ("desc", "desc", "desc")  # matches `fields` 1:1


DEFAULT_TIE_BREAK = PriorityTieBreak()
