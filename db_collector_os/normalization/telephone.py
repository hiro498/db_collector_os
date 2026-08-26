"""Lightweight telephone normalization (no external geo-phone dependency).

Produces a digits-only form with a leading '+' for numbers that already carry
a country code, and a Japan-domestic-style fallback (0-prefixed) otherwise.
This is intentionally simple: good enough for dedup/matching, not a full
libphonenumber replacement.
"""

from __future__ import annotations

import re

from .unicode import normalize_unicode

_DIGITS_RE = re.compile(r"[^\d+]")


def normalize_telephone(raw: str | None, default_country_code: str = "81") -> str:
    if not raw:
        return ""
    text = normalize_unicode(raw)
    text = _DIGITS_RE.sub("", text)
    if not text:
        return ""
    if text.startswith("+"):
        return "+" + re.sub(r"\D", "", text[1:])
    if text.startswith("00"):
        return "+" + text[2:]
    if text.startswith("0"):
        return f"+{default_country_code}" + text[1:]
    return text
