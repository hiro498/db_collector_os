"""JSON-LD structured-data extraction."""

from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from ..normalization.html_entities import decode_html_entities_deep


def extract_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        # `<script>` content is raw text per the HTML spec -- a parser never
        # HTML-decodes it the way it does ordinary text nodes. Sites whose
        # templating auto-escapes everything (including JSON payloads it
        # doesn't recognize as HTML) leave literal "&amp;"-style entities in
        # otherwise-valid JSON strings; undo that here, once, for every
        # adapter that reads these blocks.
        if isinstance(data, list):
            blocks.extend(decode_html_entities_deep(d) for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                blocks.extend(decode_html_entities_deep(d) for d in data["@graph"] if isinstance(d, dict))
            else:
                blocks.append(decode_html_entities_deep(data))
    return blocks
