"""Keyword Score computation (spec sections 21-24). Pure functions over
already-aggregated counts -- no DB/tokenizer access here -- so scoring can
be re-run (REANALYZE / "KW再計算", section 45) from stored evidence without
touching the network or re-parsing HTML.

Component budget sums to 100 before rule_boost; rule_boost is additive on
top but the final score is always capped at 100 (spec section 21/24: the
"promotion" rule_boost grants happens naturally because it raises the
capped score, which is what Importance is bucketed from).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..enums import Importance

HTML_POSITION_WEIGHTS: dict[str, int] = {
    "title": 15, "h1": 12, "url_slug": 8, "breadcrumb": 6, "category": 6,
    "tag": 5, "h2": 5, "h3": 3, "meta_description": 3, "meta_keywords": 3,
}
DEFAULT_ELEMENT_WEIGHT = 2
MAX_HTML_SCORE = 40
MAX_PHRASE_SCORE = 15
MAX_CONTENT_SCORE = 20
MAX_SITE_STRUCTURE_SCORE = 10
MAX_CROSS_PAGE_SCORE = 5

RULE_BOOST_TITLE_H1 = 5
RULE_BOOST_TITLE_SLUG = 3
RULE_BOOST_TITLE_H1_H2 = 7
RULE_BOOST_CATEGORY_MULTI_ARTICLE = 5
RULE_BOOST_TAG_MULTI_ARTICLE = 5


@dataclass
class ScoreBreakdown:
    html_score: int = 0
    content_score: int = 0
    phrase_score: int = 0
    site_structure_score: int = 0
    intent_score: int = 0
    cross_page_score: int = 0
    rule_boost: int = 0
    rule_boost_reasons: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        raw = (self.html_score + self.content_score + self.phrase_score + self.site_structure_score
               + self.intent_score + self.cross_page_score + self.rule_boost)
        return max(0, min(100, raw))

    @property
    def importance(self) -> str:
        return Importance.from_score(self.total)


def compute_html_score(element_types_present: set[str]) -> int:
    total = sum(HTML_POSITION_WEIGHTS.get(t, DEFAULT_ELEMENT_WEIGHT) for t in element_types_present)
    return min(MAX_HTML_SCORE, total)


def compute_phrase_score(token_count: int) -> int:
    return min(MAX_PHRASE_SCORE, max(0, token_count - 1) * 4)


_TFIDF_SCALE = 400.0  # calibrated so a handful of mentions of a rare term
# in a short-to-medium body page saturates the 10-point tf-idf budget
# without a single occurrence anywhere already maxing it out.
LEAD_POSITION_CHAR_THRESHOLD = 200
DISTRIBUTION_SPAN_RATIO_THRESHOLD = 0.3


def compute_content_score(
    occurrences_in_body: int,
    body_token_count: int,
    doc_freq: int,
    total_docs: int,
    first_position: int | None,
    last_position: int | None,
    body_length_chars: int,
) -> int:
    """Smoothed TF-IDF (spec section 22) plus two positional bonuses:
    an early ("本文冒頭") mention, and a mention repeated late enough in the
    body to show the term is discussed throughout ("本文全体での分布"),
    not just name-dropped once near the top.

    - tf: term frequency normalized by the page's own content-word count,
      so a term repeated in a short page scores the same as one repeated
      proportionally as often in a long page.
    - idf: standard smoothed inverse document frequency,
      ln((N+1)/(df+1)) + 1, over every analyzed page in this crawl_run.
    """
    tf = occurrences_in_body / body_token_count if body_token_count > 0 else 0.0
    idf = math.log((total_docs + 1) / (doc_freq + 1)) + 1.0 if total_docs > 0 else 1.0
    tfidf_component = min(10, round(tf * idf * _TFIDF_SCALE))

    appears_in_lead = first_position is not None and first_position < LEAD_POSITION_CHAR_THRESHOLD
    lead_bonus = 4 if appears_in_lead else 0

    distribution_bonus = 0
    if body_length_chars > 0 and first_position is not None and last_position is not None:
        span_ratio = (last_position - first_position) / body_length_chars
        if span_ratio >= DISTRIBUTION_SPAN_RATIO_THRESHOLD:
            distribution_bonus = 6
        elif occurrences_in_body >= 2:
            distribution_bonus = 3

    return min(MAX_CONTENT_SCORE, tfidf_component + lead_bonus + distribution_bonus)


def compute_site_structure_score(page_count_in_run: int) -> int:
    return min(MAX_SITE_STRUCTURE_SCORE, page_count_in_run * 2)


def compute_cross_page_score(page_count_in_run: int) -> int:
    if page_count_in_run >= 3:
        return MAX_CROSS_PAGE_SCORE
    if page_count_in_run >= 2:
        return 2
    return 0


def compute_page_level_rule_boost(title_hit: bool, h1_hit: bool, h2_count: int, url_slug_hit: bool) -> tuple[int, list[str]]:
    boost = 0
    reasons: list[str] = []
    if title_hit and h1_hit and h2_count > 0:
        boost += RULE_BOOST_TITLE_H1_H2
        reasons.append("title_h1_h2_cooccurrence")
    elif title_hit and h1_hit:
        boost += RULE_BOOST_TITLE_H1
        reasons.append("title_h1_cooccurrence")
    if title_hit and url_slug_hit:
        boost += RULE_BOOST_TITLE_SLUG
        reasons.append("title_slug_cooccurrence")
    return boost, reasons
