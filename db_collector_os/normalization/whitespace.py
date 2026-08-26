"""Whitespace normalization."""

from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")


def normalize_whitespace(text: str | None) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", text).strip()
