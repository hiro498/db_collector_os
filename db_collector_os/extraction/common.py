"""Common extraction shared by every collector type. Adapters extend this
with DB-specific fields; they should never need to re-implement title/
canonical/meta/JSON-LD/link extraction from scratch.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..normalization.html_entities import decode_html_entities
from .jsonld import extract_json_ld

_PHONE_RE = re.compile(r"(0\d{1,4}-\d{1,4}-\d{3,4}|0\d{9,10}|\+81[\d-]{9,13})")
_SOCIAL_DOMAINS = (
    "twitter.com", "x.com", "instagram.com", "facebook.com", "youtube.com",
    "tiktok.com", "line.me", "note.com",
)


def extract_common(html: str, base_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    title = _text(soup.title)
    canonical = None
    canonical_tag = soup.find("link", rel="canonical")
    if canonical_tag and canonical_tag.get("href"):
        canonical = urljoin(base_url, canonical_tag["href"])

    meta_description = None
    desc_tag = soup.find("meta", attrs={"name": "description"})
    if desc_tag and desc_tag.get("content"):
        meta_description = desc_tag["content"].strip()

    json_ld = extract_json_ld(soup)

    name = None
    address = None
    telephone = None
    for block in json_ld:
        name = name or block.get("name")
        addr = block.get("address")
        if isinstance(addr, dict):
            address = address or ", ".join(
                str(v) for v in (
                    addr.get("postalCode"), addr.get("addressRegion"),
                    addr.get("addressLocality"), addr.get("streetAddress"),
                ) if v
            )
        elif isinstance(addr, str):
            address = address or addr
        telephone = telephone or block.get("telephone")

    if not name and soup.find("h1"):
        name = _text(soup.find("h1"))

    if not telephone:
        body_text = soup.get_text(" ")
        m = _PHONE_RE.search(body_text)
        if m:
            telephone = m.group(0)

    links: list[str] = []
    social_urls: list[str] = []
    image_urls: list[str] = []

    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if href.startswith(("http://", "https://")):
            links.append(href)
            host = urlsplit(href).netloc.lower()
            if any(sd in host for sd in _SOCIAL_DOMAINS):
                social_urls.append(href)

    for img in soup.find_all("img", src=True):
        image_urls.append(urljoin(base_url, img["src"]))

    return {
        # bs4/lxml already HTML-decode ordinary text nodes and attribute
        # values, but decode_html_entities() is idempotent -- applying it
        # again here is a cheap defense against double-escaped source data
        # (e.g. a CMS that escaped a field twice) rather than a fix for a
        # known bug in this path (unlike JSON-LD; see extraction/jsonld.py).
        "title": decode_html_entities(title),
        "canonical_url": canonical or base_url,
        "meta_description": decode_html_entities(meta_description),
        "json_ld": json_ld,
        "name": decode_html_entities(name),
        "address": decode_html_entities(address),
        "telephone": telephone,
        "links": _dedupe(links)[:500],
        "social_urls": _dedupe(social_urls)[:50],
        "image_urls": _dedupe(image_urls)[:100],
    }


def _text(tag) -> str | None:
    if tag is None:
        return None
    text = tag.get_text(strip=True)
    return text or None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
