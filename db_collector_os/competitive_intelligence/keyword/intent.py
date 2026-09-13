"""Search-intent classification (spec section 25): sub-intent plus the
Know/Do/Buy/Go rollup, derived from the modifiers already detected for a
keyword plus a small set of direct action-word triggers.
"""

from __future__ import annotations

from ..enums import Intent, IntentGroup

_TRANSACTIONAL_MODIFIERS = {"price", "cheap", "coupon", "campaign", "trial"}
_TRANSACTIONAL_TERMS = ("購入", "申し込み", "申込", "予約", "注文", "公式サイト")
_COMMERCIAL_MODIFIERS = {"comparison", "ranking", "review", "reputation", "recommend", "product", "brand"}


def classify_intent(keyword_text: str, modifiers: list[str], is_local: bool, branded_type: str) -> tuple[str, str]:
    modifier_set = set(modifiers)

    if modifier_set & _TRANSACTIONAL_MODIFIERS or any(t in keyword_text for t in _TRANSACTIONAL_TERMS):
        intent = Intent.TRANSACTIONAL
    elif is_local:
        intent = Intent.LOCAL
    elif modifier_set & _COMMERCIAL_MODIFIERS:
        intent = Intent.COMMERCIAL_INVESTIGATION
    elif branded_type == "branded" and not modifier_set:
        intent = Intent.NAVIGATIONAL
    else:
        intent = Intent.INFORMATIONAL

    return intent, IntentGroup.BY_INTENT[intent]


_INTENT_SCORE_MAX10 = {
    Intent.TRANSACTIONAL: 10,
    Intent.COMMERCIAL_INVESTIGATION: 8,
    Intent.LOCAL: 6,
    Intent.NAVIGATIONAL: 4,
    Intent.INFORMATIONAL: 3,
}


def intent_score_component(intent: str) -> int:
    """The <=10-point contribution intent makes to the overall keyword
    score (spec section 21's "検索意図 最大10")."""
    return _INTENT_SCORE_MAX10.get(intent, 0)
