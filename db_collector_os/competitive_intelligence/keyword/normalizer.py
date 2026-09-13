"""Keyword text normalization + branded/local/keyword_class classification
(spec sections 18 and 27). Reuses normalization.unicode's NFKC fold
(zenkaku/hankaku unification) rather than re-implementing it.
"""

from __future__ import annotations

from ...discovery.prefecture import PREFECTURES
from ...normalization.unicode import normalize_unicode
from ..enums import BrandedType, KeywordClass
from .tokenizer import Morpheme, Tokenizer

_STATION_SUFFIX = "駅"


def normalize_keyword(text: str) -> str:
    return normalize_unicode(text).strip().lower()


def classify_branded(keyword_text: str, brand_terms: set[str]) -> str:
    if not brand_terms:
        return BrandedType.NON_BRANDED
    hits = sum(1 for term in brand_terms if term and term in keyword_text)
    if hits == 0:
        return BrandedType.NON_BRANDED
    if hits >= 1 and len(keyword_text) > max((len(t) for t in brand_terms if t in keyword_text), default=0):
        return BrandedType.MIXED
    return BrandedType.BRANDED


def detect_locality(keyword_text: str, tokenizer: Tokenizer) -> dict[str, str | bool]:
    """Best-effort: matches known prefecture names directly, and flags a
    Sudachi 地名 (place-name) morpheme or a `駅` suffix as local. City/ward
    are left unset in P0 (no ward/city gazetteer ships with CORE) rather
    than guessed.
    """
    result: dict[str, str | bool] = {"is_local": False, "prefecture": None, "city": None,
                                      "ward": None, "station": None}
    for pref in PREFECTURES:
        if pref in keyword_text:
            result["is_local"] = True
            result["prefecture"] = pref
            break

    if _STATION_SUFFIX in keyword_text:
        result["is_local"] = True
        idx = keyword_text.find(_STATION_SUFFIX)
        result["station"] = keyword_text[:idx + 1]

    if not result["is_local"]:
        for m in tokenizer.tokenize(keyword_text):
            if isinstance(m, Morpheme) and m.is_place_name:
                result["is_local"] = True
                break
    return result


def classify_keyword_class(token_count: int, modifier_count: int) -> str:
    """P0 uses token/modifier count as a proxy for head/middle/long_tail --
    spec section 27 explicitly defers volume-based classification to a
    later phase (no search-volume data source exists in this P0).
    """
    if token_count <= 1 and modifier_count == 0:
        return KeywordClass.HEAD
    if token_count <= 2 and modifier_count <= 1:
        return KeywordClass.MIDDLE
    return KeywordClass.LONG_TAIL
