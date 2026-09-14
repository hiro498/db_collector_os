"""Query fan-out subquery generation (spec section 10). Reuses the
existing keyword/modifiers.py and keyword/intent.py vocabulary rather than
inventing a second one, so a fan-out candidate's "intent_class" lines up
with the same modifier taxonomy already used to score keywords.

`covered_by_content` is a purely internal judgment -- "does this page's
own extracted keyword data already show signal for this intent class" --
never a ranking or citation claim. `serp_observed` is intentionally left
for the caller to set to None; nothing in this module may set it to True
or False, since that would require an external SERP fetch this phase
does not perform (spec section 10's explicit warning).
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import FanoutIntentClass

_TEMPLATES: dict[str, tuple[str, ...]] = {
    FanoutIntentClass.INFORMATIONAL: ("{kw}とは",),
    FanoutIntentClass.COMPARISON: ("{kw} 比較",),
    FanoutIntentClass.PRICE: ("{kw} 料金", "{kw} 価格"),
    FanoutIntentClass.REVIEW: ("{kw} 口コミ",),
    FanoutIntentClass.RANKING: ("{kw} ランキング",),
    FanoutIntentClass.BRAND: ("{kw} 公式",),
    FanoutIntentClass.LOCAL: ("{kw} 近く", "{kw} エリア"),
    FanoutIntentClass.HOWTO: ("{kw} 使い方", "{kw} やり方"),
    FanoutIntentClass.PROBLEM_SOLVING: ("{kw} 悩み",),
}

_COVERAGE_MODIFIERS: dict[str, tuple[str, ...]] = {
    FanoutIntentClass.COMPARISON: ("comparison",),
    FanoutIntentClass.PRICE: ("price", "cheap"),
    FanoutIntentClass.REVIEW: ("review", "reputation"),
    FanoutIntentClass.RANKING: ("ranking",),
    FanoutIntentClass.HOWTO: ("howto",),
    FanoutIntentClass.PROBLEM_SOLVING: ("problem",),
}


@dataclass
class FanoutCandidate:
    base_keyword: str
    subquery_text: str
    intent_class: str
    covered_by_content: bool


@dataclass
class PageIntentSignals:
    """Summary of a page's own already-scored keywords, used only to judge
    whether the page's content plausibly addresses a fan-out subquery."""
    modifiers: frozenset[str]
    has_informational: bool
    is_branded: bool
    is_local: bool


def generate_fanout_candidates(base_keyword: str, signals: PageIntentSignals) -> list[FanoutCandidate]:
    if not base_keyword:
        return []
    candidates: list[FanoutCandidate] = []
    for intent_class, templates in _TEMPLATES.items():
        covered = _is_covered(intent_class, signals)
        for template in templates:
            candidates.append(FanoutCandidate(
                base_keyword=base_keyword, subquery_text=template.format(kw=base_keyword),
                intent_class=intent_class, covered_by_content=covered,
            ))
    return candidates


def _is_covered(intent_class: str, signals: PageIntentSignals) -> bool:
    if intent_class == FanoutIntentClass.INFORMATIONAL:
        return signals.has_informational
    if intent_class == FanoutIntentClass.BRAND:
        return signals.is_branded
    if intent_class == FanoutIntentClass.LOCAL:
        return signals.is_local
    required = _COVERAGE_MODIFIERS.get(intent_class, ())
    return any(m in signals.modifiers for m in required)


def fanout_content_coverage_score(candidates: list[FanoutCandidate]) -> int:
    """0-100: share of generated intent classes the page's own content
    covers -- an internal completeness measure, never a SERP ranking claim."""
    if not candidates:
        return 0
    classes = {c.intent_class for c in candidates}
    covered_classes = {c.intent_class for c in candidates if c.covered_by_content}
    return round(100 * len(covered_classes) / len(classes)) if classes else 0
