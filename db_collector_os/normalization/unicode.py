"""Unicode normalization (NFKC), which also folds full-width Japanese
alphanumerics/punctuation to their half-width equivalents -- important for
matching addresses, phone numbers, and names scraped from Japanese sites.
"""

from __future__ import annotations

import unicodedata


def normalize_unicode(text: str | None) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text)
