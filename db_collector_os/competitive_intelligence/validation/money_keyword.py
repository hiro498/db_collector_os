"""Money/commercial keyword classification (spec section 13). Every field
here reuses an existing PHASE 1 signal -- the modifier vocabulary from
`keyword.modifiers` and the commercial_score it already produces -- rather
than introducing a new black-box judgment.
"""

from __future__ import annotations

from .config import MONEY_KEYWORD_HIGH_THRESHOLD, MONEY_KEYWORD_MEDIUM_THRESHOLD
from .enums import MoneyKeywordClass

_TRANSACTIONAL_MODIFIERS = {"price", "cheap", "coupon", "campaign", "trial"}
_REVIEW_MODIFIERS = {"review", "reputation"}
_PRICE_MODIFIERS = {"price", "cheap"}


def money_signals(modifiers: set[str]) -> dict[str, bool]:
    return {
        "transactional_signal": bool(modifiers & _TRANSACTIONAL_MODIFIERS),
        "comparison_signal": "comparison" in modifiers,
        "review_signal": bool(modifiers & _REVIEW_MODIFIERS),
        "ranking_signal": "ranking" in modifiers,
        "price_signal": bool(modifiers & _PRICE_MODIFIERS),
    }


def classify_money_keyword(commercial_score: float | None) -> str | None:
    if commercial_score is None:
        return None
    if commercial_score >= MONEY_KEYWORD_HIGH_THRESHOLD:
        return MoneyKeywordClass.HIGH
    if commercial_score >= MONEY_KEYWORD_MEDIUM_THRESHOLD:
        return MoneyKeywordClass.MEDIUM
    return MoneyKeywordClass.LOW
