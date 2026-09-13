"""HTML structure extraction (spec section 14).

Reuses extraction.common/extraction.jsonld for title/canonical/meta
description/JSON-LD rather than re-parsing those from scratch; adds every
other structural signal the keyword/scoring/classification stages need.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from ...extraction.common import extract_common
from ..url_tools import classify_non_crawlable, extract_host, is_same_host, url_slug

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_NOISE_TAGS = ("script", "style", "noscript", "template")
_CTA_PHRASES = (
    "今すぐ", "公式サイト", "公式サイトはこちら", "申し込む", "申込む", "お申込み", "購入する",
    "購入はこちら", "詳細を見る", "詳しくはこちら", "無料体験", "資料請求", "お問い合わせ",
    "予約する", "予約はこちら", "会員登録", "無料登録", "こちらから", "口コミを見る", "最安値",
    "公式", "trial", "buy now", "sign up", "read more",
)
_FAQ_HEADING_RE = re.compile(r"よくある質問|faq", re.IGNORECASE)
_POPULAR_HEADING_RE = re.compile(r"人気記事|人気ランキング")
_RELATED_HEADING_RE = re.compile(r"関連記事|あわせて読みたい|こちらもおすすめ")
_RANKING_HEADING_RE = re.compile(r"ランキング")


@dataclass
class ParsedPage:
    title: str | None = None
    meta_description: str | None = None
    meta_keywords: str | None = None
    canonical_url: str | None = None
    robots_meta: str | None = None
    og: dict[str, str] = field(default_factory=dict)
    json_ld: list[dict] = field(default_factory=list)
    published_at: str | None = None
    updated_at_source: str | None = None
    url_slug: str = ""
    indexable: bool = True
    elements: list[dict] = field(default_factory=list)
    internal_links: list[dict] = field(default_factory=list)
    outbound_links: list[dict] = field(default_factory=list)
    ctas: list[dict] = field(default_factory=list)
    # Every href seen on the page, same-host or not, before any exclusion
    # filtering -- crawler.discovery classifies each one so an out-of-scope
    # link (subdomain/external/asset/mailto/...) still gets recorded with
    # its exclusion reason (spec section 9) instead of silently vanishing.
    all_links: list[str] = field(default_factory=list)


def parse_page(html: str, url: str) -> ParsedPage:
    common = extract_common(html, url)
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    page = ParsedPage(
        title=common.get("title"),
        meta_description=common.get("meta_description"),
        canonical_url=common.get("canonical_url"),
        json_ld=common.get("json_ld", []),
        url_slug=url_slug(url),
    )
    _extract_meta(soup, page)
    _extract_headings(soup, page)
    _extract_breadcrumb(soup, page)
    _extract_body(soup, page)
    _extract_inline_emphasis(soup, page)
    _extract_tables_and_faq(soup, page)
    _extract_captions_and_alts(soup, page)
    _extract_buttons_and_cta(soup, page)
    _extract_boilerplate_containers(soup, page)
    _extract_sidebar_sections(soup, page)
    _extract_links(soup, url, page)
    _extract_category_tag(url, page)
    return page


def _add(page: ParsedPage, element_type: str, text: str | None, attrs: dict | None = None) -> None:
    if not text or not text.strip():
        return
    page.elements.append({
        "element_type": element_type,
        "position": len(page.elements),
        "text": text.strip(),
        "attrs": attrs or {},
    })


def _extract_meta(soup: BeautifulSoup, page: ParsedPage) -> None:
    kw_tag = soup.find("meta", attrs={"name": "keywords"})
    if kw_tag and kw_tag.get("content"):
        page.meta_keywords = kw_tag["content"].strip()
        _add(page, "meta_keywords", page.meta_keywords)
    if page.meta_description:
        _add(page, "meta_description", page.meta_description)

    robots_tag = soup.find("meta", attrs={"name": "robots"})
    if robots_tag and robots_tag.get("content"):
        page.robots_meta = robots_tag["content"].strip()
        page.indexable = "noindex" not in page.robots_meta.lower()

    for og_tag in soup.find_all("meta", attrs={"property": re.compile(r"^og:")}):
        key = og_tag.get("property", "")
        if og_tag.get("content"):
            page.og[key] = og_tag["content"].strip()
    for key, value in page.og.items():
        _add(page, f"og:{key.split(':', 1)[-1]}", value)

    for time_tag in soup.find_all("time"):
        dt = time_tag.get("datetime") or time_tag.get_text(strip=True)
        cls = " ".join(time_tag.get("class", [])).lower()
        if "update" in cls or "modif" in cls:
            page.updated_at_source = page.updated_at_source or dt
        else:
            page.published_at = page.published_at or dt
    for block in page.json_ld:
        page.published_at = page.published_at or block.get("datePublished")
        page.updated_at_source = page.updated_at_source or block.get("dateModified")


def _extract_headings(soup: BeautifulSoup, page: ParsedPage) -> None:
    if page.title:
        _add(page, "title", page.title)
    for level in _HEADING_TAGS:
        for tag in soup.find_all(level):
            _add(page, level, tag.get_text(" ", strip=True))


def _extract_breadcrumb(soup: BeautifulSoup, page: ParsedPage) -> None:
    candidate = soup.find(attrs={"aria-label": re.compile("breadcrumb", re.IGNORECASE)})
    if candidate is None:
        candidate = soup.find(class_=re.compile("breadcrumb", re.IGNORECASE))
    if candidate is None:
        for block in page.json_ld:
            if block.get("@type") == "BreadcrumbList":
                items = block.get("itemListElement") or []
                names = [i.get("name") for i in items if isinstance(i, dict) and i.get("name")]
                if names:
                    _add(page, "breadcrumb", " > ".join(names))
                return
        return
    text = " > ".join(p.strip() for p in candidate.get_text("|", strip=True).split("|") if p.strip())
    _add(page, "breadcrumb", text)


def _main_content_root(soup: BeautifulSoup) -> Tag:
    for selector in ("main", "article", '[role="main"]'):
        found = soup.select_one(selector)
        if found is not None:
            return found
    return soup.body or soup


def _extract_body(soup: BeautifulSoup, page: ParsedPage) -> None:
    root = _main_content_root(soup)
    for tag in root.find_all(("nav", "header", "footer", "aside", "form")):
        tag.decompose()
    paragraphs = [p.get_text(" ", strip=True) for p in root.find_all("p")]
    paragraphs = [p for p in paragraphs if p]
    body_text = " ".join(paragraphs) if paragraphs else root.get_text(" ", strip=True)
    if not body_text:
        return
    _add(page, "body", body_text)
    _add(page, "body_lead", body_text[:200])


def _extract_inline_emphasis(soup: BeautifulSoup, page: ParsedPage) -> None:
    for tag in soup.find_all(("strong", "b", "em")):
        _add(page, "strong", tag.get_text(" ", strip=True))


def _extract_tables_and_faq(soup: BeautifulSoup, page: ParsedPage) -> None:
    for table in soup.find_all("table"):
        caption = table.find("caption")
        header_cells = table.find_all("th")
        parts = []
        if caption:
            parts.append(caption.get_text(" ", strip=True))
        parts.extend(c.get_text(" ", strip=True) for c in header_cells[:10])
        if parts:
            _add(page, "table", " / ".join(p for p in parts if p))

    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                _add(page, "faq", f"Q: {dt.get_text(' ', strip=True)} A: {dd.get_text(' ', strip=True)}")

    for heading in soup.find_all(_HEADING_TAGS):
        if _FAQ_HEADING_RE.search(heading.get_text(strip=True)):
            _add(page, "faq", heading.get_text(" ", strip=True))

    for block in page.json_ld:
        if block.get("@type") == "FAQPage":
            for item in block.get("mainEntity") or []:
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "")
                answer = (item.get("acceptedAnswer") or {}).get("text", "")
                if name:
                    _add(page, "faq", f"Q: {name} A: {answer}")


def _extract_captions_and_alts(soup: BeautifulSoup, page: ParsedPage) -> None:
    for cap in soup.find_all(("figcaption", "caption")):
        _add(page, "caption", cap.get_text(" ", strip=True))
    for img in soup.find_all("img", alt=True):
        if img["alt"].strip():
            _add(page, "alt", img["alt"].strip())


def _extract_buttons_and_cta(soup: BeautifulSoup, page: ParsedPage) -> None:
    for btn in soup.find_all("button"):
        text = btn.get_text(" ", strip=True)
        if text:
            _add(page, "button", text)

    seen_cta_positions: set[int] = set()
    for tag in soup.find_all(("a", "button")):
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        classes = " ".join(tag.get("class", [])).lower()
        is_cta_class = "cta" in classes or "btn" in classes
        is_cta_phrase = any(phrase in text for phrase in _CTA_PHRASES) or any(
            phrase.lower() in text.lower() for phrase in _CTA_PHRASES
        )
        if not (is_cta_class or is_cta_phrase):
            continue
        href = tag.get("href")
        position = len(page.ctas)
        if position in seen_cta_positions:
            continue
        page.ctas.append({
            "cta_text": text,
            "target_url": href,
            "target_domain": extract_host(href) if href and href.startswith("http") else None,
            "cta_type": "button" if tag.name == "button" else "link",
            "position": position,
        })


def _extract_boilerplate_containers(soup: BeautifulSoup, page: ParsedPage) -> None:
    for tag_name, element_type in (("nav", "nav"), ("header", "header"), ("footer", "footer")):
        for tag in soup.find_all(tag_name):
            _add(page, element_type, tag.get_text(" ", strip=True))
    for cookie in soup.find_all(class_=re.compile("cookie", re.IGNORECASE)):
        _add(page, "cookie_notice", cookie.get_text(" ", strip=True))


def _extract_sidebar_sections(soup: BeautifulSoup, page: ParsedPage) -> None:
    for aside in soup.find_all("aside"):
        _add(page, "sidebar", aside.get_text(" ", strip=True)[:1000])
    for heading in soup.find_all(_HEADING_TAGS):
        text = heading.get_text(strip=True)
        if _POPULAR_HEADING_RE.search(text):
            _add(page, "popular_articles_heading", text)
        elif _RELATED_HEADING_RE.search(text):
            _add(page, "related_articles_heading", text)
        elif _RANKING_HEADING_RE.search(text):
            _add(page, "ranking_heading", text)


def _extract_links(soup: BeautifulSoup, base_url: str, page: ParsedPage) -> None:
    base_host = extract_host(base_url)
    for pos, a in enumerate(soup.find_all("a", href=True)):
        href = a["href"].strip()
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(base_url, href)
        anchor_text = a.get_text(" ", strip=True)
        nofollow = "nofollow" in (a.get("rel") or [])
        _add(page, "anchor", anchor_text, {"href": absolute})
        page.all_links.append(absolute)

        exclusion = classify_non_crawlable(absolute, base_host)
        if exclusion in ("mailto", "tel", "javascript_url", "non_html_asset"):
            continue
        if is_same_host(absolute, base_host):
            page.internal_links.append({
                "target_url": absolute, "anchor_text": anchor_text, "position": pos, "nofollow": nofollow,
            })
        else:
            page.outbound_links.append({
                "url": absolute, "target_domain": extract_host(absolute),
                "anchor_text": anchor_text, "position": pos,
            })


def _extract_category_tag(url: str, page: ParsedPage) -> None:
    path = urlsplit(url).path
    match = re.search(r"/(category|categories|cat)/([^/]+)/?", path, re.IGNORECASE)
    if match:
        _add(page, "category", match.group(2).replace("-", " ").replace("_", " "))
    match = re.search(r"/tags?/([^/]+)/?", path, re.IGNORECASE)
    if match:
        _add(page, "tag", match.group(1).replace("-", " ").replace("_", " "))
    if page.url_slug:
        _add(page, "url_slug", page.url_slug.replace("-", " ").replace("_", " "))
