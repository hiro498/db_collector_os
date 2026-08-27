"""Best-effort extraction from a page's `dataLayer` (Google Analytics 4
Enhanced Ecommerce convention -- item_id/item_name/item_brand/item_category/
item_category2/price/... are GA4's own standard item-scoped parameter names,
see https://developers.google.com/analytics/devguides/collection/ga4/ecommerce
-- not a site-specific structure).

This is intentionally conservative: only `dataLayer.push({...})` calls whose
argument is a *strictly valid JSON* object literal are parsed. Real-world
dataLayer scripts sometimes use unquoted keys, single-quoted strings, or JS
expressions that aren't valid JSON -- those are silently skipped rather than
guessed at with a looser parser, since a wrong guess here would quietly
corrupt adapter field data. JSON-LD remains the authoritative source
wherever both are available; this is a fallback for fields JSON-LD omits.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..normalization.html_entities import decode_html_entities_deep

_PUSH_RE = re.compile(r"dataLayer\.push\s*\(", re.IGNORECASE)


def extract_data_layer_items(html: str) -> list[dict[str, Any]]:
    """Return one flattened dict per ecommerce item found across every
    `dataLayer.push({...})` call in the page. Any top-level keys alongside
    `ecommerce` in the same push (e.g. a site's own custom fields) are
    merged into each item, since those commonly describe the same product.
    """
    if not html:
        return []
    items: list[dict[str, Any]] = []
    for match in _PUSH_RE.finditer(html):
        obj_str = _extract_balanced_object(html, match.end())
        if obj_str is None:
            continue
        try:
            payload = json.loads(obj_str)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        payload = decode_html_entities_deep(payload)
        ecommerce = payload.get("ecommerce")
        context = {k: v for k, v in payload.items() if k != "ecommerce"}
        if isinstance(ecommerce, dict) and isinstance(ecommerce.get("items"), list):
            for item in ecommerce["items"]:
                if isinstance(item, dict):
                    items.append({**context, **item})
        elif context:
            items.append(context)
    return items


def _extract_balanced_object(text: str, start: int) -> str | None:
    """Starting just past `dataLayer.push(`, return the raw text of the
    `{...}` object literal passed as the argument, honoring nested braces
    and quoted strings, or None if the argument isn't an object literal at
    all (e.g. an array push, a bare variable).
    """
    i = start
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text) or text[i] != "{":
        return None

    depth = 0
    in_string = False
    string_char = ""
    escape = False
    for j in range(i, len(text)):
        ch = text[j]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == string_char:
                in_string = False
            continue
        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[i : j + 1]
    return None
