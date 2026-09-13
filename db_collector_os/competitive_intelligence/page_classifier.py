"""Page-type classification (spec section 16): multiple weak signals summed
into a 0-100 confidence per candidate type, rather than a single rule
deciding the outcome. Low-signal pages are reported as `other` with their
true (low) confidence instead of being forced into a guessed category --
see spec section 16, "do not force a low-confidence decision".

Takes plain `elements`/`json_ld` rather than a `parser.ParsedPage`, so the
exact same function classifies a freshly-parsed page and a page rebuilt
from stored `ci_page_elements` rows (the REANALYZE path, spec section 45,
which never re-parses HTML).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .enums import PageType

_MIN_CONFIDENCE_TO_COMMIT = 30

_URL_PATTERNS: dict[str, re.Pattern] = {
    PageType.COMPANY: re.compile(r"/(company|about|corporate|会社概要)", re.IGNORECASE),
    PageType.CONTACT: re.compile(r"/(contact|inquiry|otoiawase)", re.IGNORECASE),
    PageType.PRIVACY: re.compile(r"/(privacy|privacy-policy)", re.IGNORECASE),
    PageType.TERMS: re.compile(r"/(terms|kiyaku|rule)", re.IGNORECASE),
    PageType.LOGIN: re.compile(r"/(login|signin|mypage|register)", re.IGNORECASE),
    PageType.CATEGORY: re.compile(r"/(category|categories|cat)/", re.IGNORECASE),
    PageType.TAG: re.compile(r"/(tag|tags)/", re.IGNORECASE),
    PageType.RANKING: re.compile(r"/(ranking|rank)", re.IGNORECASE),
    PageType.COMPARISON: re.compile(r"/(compare|comparison|hikaku)", re.IGNORECASE),
    PageType.REVIEW: re.compile(r"/(review|kuchikomi)", re.IGNORECASE),
}

_TEXT_KEYWORDS: dict[str, tuple[str, ...]] = {
    PageType.RANKING: ("ランキング", "best10", "トップ10", "ベスト"),
    PageType.COMPARISON: ("比較", "くらべ", " vs "),
    PageType.REVIEW: ("レビュー", "口コミ", "評判", "感想"),
    PageType.COMPANY: ("会社概要", "企業情報", "運営会社", "運営者情報"),
    PageType.CONTACT: ("お問い合わせ", "コンタクト"),
    PageType.PRIVACY: ("プライバシーポリシー", "個人情報保護方針"),
    PageType.TERMS: ("利用規約", "ご利用規約"),
    PageType.LOGIN: ("ログイン", "会員登録", "マイページ"),
    PageType.PRODUCT_SERVICE: ("価格", "料金プラン", "商品詳細", "スペック"),
}

_SCHEMA_TYPE_MAP = {
    "Article": PageType.ARTICLE,
    "NewsArticle": PageType.ARTICLE,
    "BlogPosting": PageType.ARTICLE,
    "Product": PageType.PRODUCT_SERVICE,
    "Offer": PageType.PRODUCT_SERVICE,
    "CollectionPage": PageType.CATEGORY,
}


def classify(
    elements: list[dict],
    json_ld: list[dict],
    title: str | None,
    url: str,
    cta_count: int = 0,
    outbound_affiliate_ratio: float = 0.0,
) -> tuple[str, int]:
    scores: dict[str, int] = {t: 0 for t in PageType.ALL}
    path = urlsplit(url).path

    if path in ("", "/"):
        scores[PageType.TOP] += 60

    for page_type, pattern in _URL_PATTERNS.items():
        if pattern.search(path):
            scores[page_type] += 45

    title_and_h1 = " ".join(filter(None, [title, _first_text(elements, "h1")]))
    for page_type, keywords in _TEXT_KEYWORDS.items():
        if any(kw in title_and_h1 for kw in keywords):
            scores[page_type] += 35

    for block in json_ld:
        mapped = _SCHEMA_TYPE_MAP.get(block.get("@type"))
        if mapped:
            scores[mapped] += 25
        if block.get("@type") == "FAQPage":
            scores[PageType.ARTICLE] += 10

    table_count = sum(1 for e in elements if e["element_type"] == "table")
    faq_count = sum(1 for e in elements if e["element_type"] == "faq")
    body = _first_text(elements, "body") or ""

    if table_count >= 1 and scores[PageType.COMPARISON] > 0:
        scores[PageType.COMPARISON] += 20
    if faq_count >= 2:
        scores[PageType.ARTICLE] += 10
    if cta_count >= 3 and len(body) < 400 and outbound_affiliate_ratio > 0.3:
        scores[PageType.LP] += 40
    # A page with a real h1 and a substantive body, and no heavy-CTA/LP
    # signal, is ordinary editorial content -- the common case for an
    # affiliate site's articles, most of which carry no schema.org markup
    # at all. Without this, any plain article with no JSON-LD/FAQ/ranking
    # keyword would fall through to `other` below the commit threshold,
    # even though "it's just an article" is the obviously correct read.
    # This never outranks a more specific signal (top/ranking/comparison/
    # review/company/... all score higher already) -- it only rescues the
    # otherwise-signal-less case.
    if len(body) > 150 and cta_count <= 2 and _first_text(elements, "h1"):
        scores[PageType.ARTICLE] += 30
    if len(body) > 800 and cta_count == 0:
        scores[PageType.ARTICLE] += 10

    best_type = max(scores, key=lambda t: scores[t])
    best_score = min(100, scores[best_type])
    if best_score < _MIN_CONFIDENCE_TO_COMMIT:
        return PageType.OTHER, best_score
    return best_type, best_score


def is_seo_analysis_target(page_type: str, confidence: int, indexable: bool) -> bool:
    if not indexable:
        return False
    if page_type in PageType.ANALYSIS_EXCLUDED:
        return False
    if page_type in PageType.ANALYSIS_INCLUDED:
        return True
    if page_type == PageType.OTHER:
        return confidence >= PageType.OTHER_INCLUSION_CONFIDENCE_MIN
    return False


def _first_text(elements: list[dict], element_type: str) -> str | None:
    for el in elements:
        if el["element_type"] == element_type:
            return el["text"]
    return None
