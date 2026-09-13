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

from dataclasses import dataclass, field

from ..enums import Importance

HTML_POSITION_WEIGHTS: dict[str, int] = {
    "title": 15, "h1": 12, "url_slug": 8, "breadcrumb": 6, "category": 6,
    "tag": 5, "h2": 5, "h3": 3, "meta_description": 3,
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


def compute_content_score(
    occurrences_in_body: int, doc_freq: int, total_docs: int, appears_in_lead: bool
) -> int:
    tf_component = min(12, occurrences_in_body * 3)
    rarity = 1.0 - (doc_freq / total_docs) if total_docs > 0 else 0.0
    idf_component = round(max(0.0, rarity) * 5)
    lead_bonus = 3 if appears_in_lead else 0
    return min(MAX_CONTENT_SCORE, tf_component + idf_component + lead_bonus)


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
