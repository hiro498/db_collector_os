"""LLM-based keyword candidate *suggestion* (not volume data) -- optional
supplement to the combinatorial generator in keyword_generator.py, per spec
section 2's "補助: Gemini等によるキーワード候補補完".

This never runs automatically and defaults to a safe no-op
(NullKeywordExpander) exactly like NullSearchProvider /
NullKeywordSource -- a missing API key must never break Phase 1. Wiring a
real LLM call here (Gemini, or the Claude API already used to run this
project) is a small, optional follow-up once the operator decides which
provider/key to use; see docs/db_viability_tool.md.
"""

from __future__ import annotations

from typing import Protocol


class KeywordExpander(Protocol):
    def suggest(self, theme_name: str, existing_keywords: list[str], max_suggestions: int = 20) -> list[str]:
        """Return additional candidate keyword strings (no volume data --
        those still need a KeywordSource lookup). Must never raise for a
        missing/invalid config; return [] instead.
        """
        ...


class NullKeywordExpander:
    def suggest(self, theme_name: str, existing_keywords: list[str], max_suggestions: int = 20) -> list[str]:
        return []
