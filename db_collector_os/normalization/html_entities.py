"""HTML entity decoding.

Some sites HTML-escape text even where it doesn't belong -- most commonly
inside a `<script type="application/ld+json">` block, where a templating
engine's default auto-escaping ran over the JSON payload without knowing
its content wasn't HTML. `<script>` content is "raw text" per the HTML
spec, so a parser never decodes entities inside it the way it does for
ordinary text nodes -- a naively-templated JSON-LD `name` field like
"Rikka Takarada &amp; Akane Shinjo" survives `json.loads()` verbatim,
entity and all. This module normalizes that away.
"""

from __future__ import annotations

import html
from typing import Any


def decode_html_entities(text: str | None) -> str | None:
    """Decode HTML/XML entities (named and numeric) in a plain string.
    Idempotent: text with no entities, or already-decoded text, passes
    through unchanged -- safe to apply defensively even where the source
    is already known-clean.
    """
    if not text:
        return text
    return html.unescape(text)


def decode_html_entities_deep(value: Any) -> Any:
    """Recursively decode HTML entities in every string found inside a
    JSON-like structure (dicts/lists of str/int/float/bool/None), leaving
    keys and non-string values untouched. Used on parsed JSON-LD blocks,
    where a `brand.name`, `offers.price`, or `image` list entry can each
    independently carry escaped entities.
    """
    if isinstance(value, str):
        return html.unescape(value)
    if isinstance(value, list):
        return [decode_html_entities_deep(item) for item in value]
    if isinstance(value, dict):
        return {key: decode_html_entities_deep(val) for key, val in value.items()}
    return value
