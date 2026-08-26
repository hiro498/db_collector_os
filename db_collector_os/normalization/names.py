"""Entity/company name normalization for matching and dedup fingerprints."""

from __future__ import annotations

import re

from .unicode import normalize_unicode
from .whitespace import normalize_whitespace

_CORP_SUFFIXES = [
    "株式会社", "有限会社", "合同会社", "合資会社", "合名会社",
    "co., ltd.", "co.,ltd.", "co ltd", "inc.", "inc", "corp.", "corp",
    "corporation", "company", "llc", "ltd.", "ltd",
]

_PUNCT_RE = re.compile(r"[　\s\-_/,.。、･・()（）【】\[\]]+")


def normalize_name(raw: str | None) -> str:
    """Produce a matching key: unicode-folded, suffix-stripped, punctuation
    collapsed, lowercased. The original `name` field is preserved separately;
    this is only used for fingerprints/dedup, never displayed.
    """
    if not raw:
        return ""
    text = normalize_unicode(raw).lower()
    text = normalize_whitespace(text)
    for suffix in _CORP_SUFFIXES:
        text = text.replace(suffix, " ")
    text = _PUNCT_RE.sub("", text)
    return text.strip()
