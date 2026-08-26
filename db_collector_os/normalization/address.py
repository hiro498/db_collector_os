"""Address normalization: unicode fold + whitespace collapse + a couple of
common Japanese-address punctuation variants collapsed to one form.
"""

from __future__ import annotations

import re

from .unicode import normalize_unicode
from .whitespace import normalize_whitespace

_HYPHEN_VARIANTS = re.compile(r"[‐‑‒–—―ー−]")


def normalize_address(raw: str | None) -> str:
    if not raw:
        return ""
    text = normalize_unicode(raw)
    text = _HYPHEN_VARIANTS.sub("-", text)
    text = normalize_whitespace(text)
    return text
