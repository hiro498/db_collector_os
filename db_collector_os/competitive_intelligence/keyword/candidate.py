"""1-5 word keyword candidate generation (spec section 19-20).

Candidates are windows over *contiguous runs of content words* (noun/
proper-noun/verbal-noun/verb/adjective/numeral), never arbitrary token
combinations -- this is what keeps generation linear (each run of length L
yields O(L * max_len) candidates) instead of exploding combinatorially, and
what keeps candidates readable as real compound queries rather than
grammatically-broken word soup (particles/symbols always break a run).
"""

from __future__ import annotations

from dataclasses import dataclass

from .tokenizer import Morpheme, Tokenizer

MAX_NGRAM = 5


@dataclass
class Candidate:
    text: str
    token_count: int
    start_offset: int


def generate_candidates(text: str, tokenizer: Tokenizer, max_len: int = MAX_NGRAM) -> list[Candidate]:
    if not text:
        return []
    morphemes = tokenizer.tokenize(text)
    positioned = _with_offsets(text, morphemes)
    runs = _content_runs(positioned)

    candidates: list[Candidate] = []
    for run in runs:
        n = len(run)
        for length in range(1, min(max_len, n) + 1):
            for start in range(0, n - length + 1):
                window = run[start:start + length]
                surface = "".join(m.surface for _, m in window)
                offset = window[0][0]
                candidates.append(Candidate(text=surface, token_count=length, start_offset=offset))
    return candidates


def _with_offsets(text: str, morphemes: list[Morpheme]) -> list[tuple[int, Morpheme]]:
    cursor = 0
    out = []
    for m in morphemes:
        idx = text.find(m.surface, cursor)
        if idx == -1:
            idx = cursor
        out.append((idx, m))
        cursor = idx + len(m.surface)
    return out


def _content_runs(positioned: list[tuple[int, Morpheme]]) -> list[list[tuple[int, Morpheme]]]:
    runs: list[list[tuple[int, Morpheme]]] = []
    current: list[tuple[int, Morpheme]] = []
    for offset, m in positioned:
        if m.is_content:
            current.append((offset, m))
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs
