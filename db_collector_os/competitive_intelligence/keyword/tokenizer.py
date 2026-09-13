"""Japanese morphological tokenization (spec section 18).

SudachiPy is the first-choice backend (added as the optional `ci` extra in
pyproject.toml so installing db_collector_os for the existing entity-
collection use case never pulls in a ~70MB dictionary it doesn't need). A
regex-based fallback keeps candidate generation and every downstream stage
working even where SudachiPy/its dictionary isn't installed, deterministic
enough for unit tests to target directly.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Protocol

# Sudachi POS tags this package treats as "content" (keyword-bearing) words,
# per spec section 18's required coverage (noun/proper-noun/verbal-noun/
# verb/adjective/numeral).
CONTENT_POS1 = {"名詞", "動詞", "形容詞"}
PROPER_NOUN_POS2 = {"固有名詞"}
PLACE_NAME_POS3 = {"地名"}
PERSON_NAME_POS3 = {"人名"}
SAHEN_POS3 = {"サ変可能", "サ変形状詞可能"}
NUMERAL_POS2 = {"数詞"}


@dataclass
class Morpheme:
    surface: str
    normalized: str
    pos1: str  # e.g. 名詞/動詞/形容詞/助詞/記号/...
    pos2: str = ""
    pos3: str = ""

    @property
    def is_content(self) -> bool:
        return self.pos1 in CONTENT_POS1

    @property
    def is_proper_noun(self) -> bool:
        return self.pos2 in PROPER_NOUN_POS2

    @property
    def is_place_name(self) -> bool:
        return self.pos3 in PLACE_NAME_POS3

    @property
    def is_person_name(self) -> bool:
        return self.pos3 in PERSON_NAME_POS3

    @property
    def is_numeral(self) -> bool:
        return self.pos2 in NUMERAL_POS2


class Tokenizer(Protocol):
    def tokenize(self, text: str) -> list[Morpheme]: ...


class SudachiTokenizer:
    """Split-mode C (longest unit) -- the mode most appropriate for
    compound-keyword recovery rather than search-index-style short units.
    """

    def __init__(self) -> None:
        from sudachipy import dictionary, tokenizer  # noqa: F401 -- import errors bubble to the factory

        self._sudachi_tokenizer_mode = tokenizer.Tokenizer.SplitMode.C
        self._dictionary = dictionary.Dictionary().create()

    def tokenize(self, text: str) -> list[Morpheme]:
        if not text:
            return []
        out = []
        for m in self._dictionary.tokenize(text, self._sudachi_tokenizer_mode):
            pos = m.part_of_speech()
            out.append(Morpheme(
                surface=m.surface(), normalized=m.normalized_form(),
                pos1=pos[0], pos2=pos[1] if len(pos) > 1 else "", pos3=pos[2] if len(pos) > 2 else "",
            ))
        return out


# Character classes used to segment text without any morphological
# knowledge -- hiragana/katakana/kanji/alnum runs are treated as one
# "content" morpheme each, everything else (punctuation, symbols, spaces)
# is a boundary. This intentionally cannot do the fine-grained POS split
# Sudachi does; it exists so the rest of the pipeline (candidate n-grams,
# scoring, intent) keeps working without the optional dependency installed.
_RUN_RE = re.compile(
    r"[ぁ-んー]+|[ァ-ヴー]+|[一-龯々]+|[A-Za-z0-9]+"
)


class RegexFallbackTokenizer:
    def tokenize(self, text: str) -> list[Morpheme]:
        if not text:
            return []
        return [
            Morpheme(surface=m.group(0), normalized=m.group(0), pos1="名詞")
            for m in _RUN_RE.finditer(text)
        ]


_lock = threading.Lock()
_default_tokenizer: Tokenizer | None = None


def get_default_tokenizer() -> Tokenizer:
    global _default_tokenizer
    if _default_tokenizer is not None:
        return _default_tokenizer
    with _lock:
        if _default_tokenizer is not None:
            return _default_tokenizer
        try:
            _default_tokenizer = SudachiTokenizer()
        except Exception:
            _default_tokenizer = RegexFallbackTokenizer()
    return _default_tokenizer
