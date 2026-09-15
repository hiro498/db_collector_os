"""Noise audit (spec section 11). PHASE 1's boilerplate detector
(`parser.boilerplate.detect_and_mark_boilerplate`) already excludes
repeated nav/footer/CTA elements from keyword candidate generation
upstream of everything in this package -- this module is a second,
independent safety net that flags a keyword by its own *surface text*
(e.g. a legitimate, non-repeated page genuinely titled "利用規約" would
still produce that keyword), so the two layers catch different cases
rather than one re-implementing the other.
"""

from __future__ import annotations

from .config import NOISE_EXACT_TERMS, NOISE_MIN_TEXT_LENGTH, NOISE_TEXT_PATTERNS


def _is_kanji(ch: str) -> bool:
    return "一" <= ch <= "鿿"


# spec section 11's "不自然なn-gram" (unnatural n-gram): a Japanese suru-verb
# ("解説する" -> "解説し(ています)") tokenizes into a noun morpheme plus a
# bare verb-continuative morpheme, so an n-gram window can produce
# "解説し" as its own candidate even though "解説" is the real word. Any of
# these single-mora continuative endings, on a keyword whose text minus
# that final character is ALSO itself a known candidate, names the whole
# thing an artifact of that verb form rather than an independent term.
_VERB_CONTINUATIVE_ENDINGS = ("し", "り", "き", "ぎ", "み", "ち", "に", "び", "げ")


def detect_unnatural_ngram(keyword_text: str, other_normalized_keywords: set[str]) -> tuple[bool, str | None]:
    text = (keyword_text or "").strip()
    if len(text) < 2 or text[-1] not in _VERB_CONTINUATIVE_ENDINGS:
        return False, None
    stem = text[:-1]
    if stem in other_normalized_keywords:
        return True, f"unnatural_ngram:verb_fragment_of:{stem}"
    return False, None


def detect_noise(keyword_text: str) -> tuple[bool, str | None]:
    text = (keyword_text or "").strip()
    # A single hiragana/katakana/ASCII character is almost always a
    # grammatical fragment (a particle, a verb-conjugation tail from an
    # occasional tokenizer mis-segmentation) -- but a single kanji
    # character is very often a real, meaningful noun in Japanese (枕,
    # 靴, 髪, ...), so the short-length check only applies to the former.
    if len(text) < NOISE_MIN_TEXT_LENGTH and not (len(text) == 1 and _is_kanji(text)):
        return True, "too_short"
    if text in NOISE_EXACT_TERMS:
        return True, f"generic_scaffolding_term:{text}"
    lowered = text.lower()
    for pattern in NOISE_TEXT_PATTERNS:
        if pattern in text or pattern in lowered:
            return True, f"boilerplate_term:{pattern}"
    return False, None
