"""Search-modifier dictionary (spec section 26). Extensible: a VerticalProfile
may contribute additional {modifier: [terms]} entries via
`vertical.extra_modifier_terms()`, merged on top of this CORE dictionary --
CORE itself never hardcodes a genre-specific term here.
"""

from __future__ import annotations

from ..vertical.base import VerticalProfile, get_vertical

MODIFIER_TERMS: dict[str, tuple[str, ...]] = {
    "recommend": ("おすすめ", "オススメ", "お勧め"),
    "comparison": ("比較", "くらべ"),
    "ranking": ("ランキング", "ベスト", "トップ10"),
    "review": ("レビュー", "口コミ"),
    "reputation": ("評判",),
    "price": ("価格", "値段", "料金"),
    "cheap": ("安い", "激安", "格安"),
    "coupon": ("クーポン",),
    "campaign": ("キャンペーン",),
    "trial": ("体験", "トライアル", "お試し"),
    "area": ("エリア", "地域"),
    "station": ("駅",),
    "age": ("代", "歳"),
    "gender": ("メンズ", "レディース", "男性", "女性"),
    "problem": ("悩み", "トラブル", "原因"),
    "howto": ("方法", "やり方", "使い方"),
    "difference": ("違い",),
    "meaning": ("意味", "とは"),
    "latest": ("最新",),
    "free": ("無料",),
    "product": ("商品", "製品"),
}

# These modifiers signal purchase-adjacent intent more strongly than the
# purely informational ones; weights feed commercial_score (max 100).
_COMMERCIAL_WEIGHT = {
    "price": 20, "cheap": 20, "coupon": 25, "campaign": 20, "trial": 15,
    "comparison": 15, "ranking": 10, "review": 10, "reputation": 10,
    "recommend": 10, "product": 10, "brand": 10,
}
_INFORMATIONAL_WEIGHT = {
    "howto": -5, "meaning": -10, "difference": -5, "latest": -2,
    "free": 5, "area": 2, "station": 2, "age": 0, "gender": 0, "problem": -2,
}


def detect_modifiers(keyword_text: str, vertical: VerticalProfile | None = None) -> list[str]:
    terms = dict(MODIFIER_TERMS)
    if vertical is not None:
        for key, extra in vertical.extra_modifier_terms().items():
            terms[key] = tuple(terms.get(key, ())) + tuple(extra)
    brand_terms = vertical.brand_terms() if vertical is not None else set()
    if any(term and term in keyword_text for term in brand_terms):
        terms = {**terms, "brand": ()}

    hits = []
    for modifier, triggers in terms.items():
        if modifier == "brand":
            hits.append(modifier)
            continue
        if any(trigger in keyword_text for trigger in triggers):
            hits.append(modifier)
    return sorted(hits)


def commercial_score(modifiers: list[str]) -> int:
    if not modifiers:
        return 0
    score = sum(_COMMERCIAL_WEIGHT.get(m, 0) + _INFORMATIONAL_WEIGHT.get(m, 0) for m in modifiers)
    return max(0, min(100, score))


def get_default_vertical() -> VerticalProfile:
    return get_vertical(None)
