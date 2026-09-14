"""Shared tokenizer-based text-region helpers for the AI Search Analysis
module. Reuses keyword.tokenizer rather than approximating "N words" with
a fixed character count -- Japanese has no whitespace word boundaries, so
a naive character slice would cut words in half unpredictably.
"""

from __future__ import annotations

from ..keyword.tokenizer import get_default_tokenizer


def lead_text(text: str, word_count: int) -> str:
    """Returns the prefix of `text` covering roughly the first
    `word_count` content words (nouns/verbs/adjectives/numerals),
    including the non-content text (particles, punctuation) interleaved
    between them, so the excerpt still reads naturally.
    """
    if not text:
        return ""
    tokenizer = get_default_tokenizer()
    morphemes = tokenizer.tokenize(text)
    content_seen = 0
    cursor = 0
    end = len(text)
    for m in morphemes:
        idx = text.find(m.surface, cursor)
        if idx == -1:
            idx = cursor
        cursor = idx + len(m.surface)
        if m.is_content:
            content_seen += 1
            if content_seen >= word_count:
                end = cursor
                break
    else:
        end = len(text)
    return text[:end]


def proper_noun_count(text: str) -> int:
    if not text:
        return 0
    tokenizer = get_default_tokenizer()
    return sum(1 for m in tokenizer.tokenize(text) if m.is_proper_noun)
