"""Fetch wrapper: reuses fetching.client.FetchEngine as-is (robots.txt, SSRF
guard, charset sniffing, timeout, CAPTCHA detection are all already handled
there -- see spec section 10, "do not reimplement"). This module only adds:

- a thin `PageFetchResult` the crawler can act on without importing
  fetching.client.FetchResult's dataclass directly, and
- the JS-rendering fallback abstraction (`JSFallbackFetcher`), whose
  default implementation is intentionally a no-op that reports
  "unavailable" rather than shipping an unrequested Playwright dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..fetching.client import FetchEngine, FetchResult

# Below this many visible characters of extracted body text, a normal HTTP
# fetch is considered too thin to analyze and JS-fallback becomes eligible
# (spec section 10: "fallback only when body extraction essentially fails").
THIN_CONTENT_CHAR_THRESHOLD = 200


@dataclass
class PageFetchResult:
    ok: bool
    http_status: int | None
    final_url: str | None
    html: str | None
    error: str | None
    blocked: bool
    js_fallback_used: bool = False
    js_fallback_available: bool = False


class JSFallbackFetcher(Protocol):
    def render(self, url: str) -> str | None:
        """Return rendered HTML, or None if rendering failed/unavailable."""
        ...


class UnavailableJSFallbackFetcher:
    """Default JS fallback: always unavailable. Selecting a real renderer
    (e.g. Playwright) is an explicit, separate decision -- see spec section
    10, "confirm impact on existing dependencies before introducing
    Playwright". Nothing in this P0 imports playwright.
    """

    def render(self, url: str) -> str | None:
        return None


def fetch_page(
    fetch_engine: FetchEngine,
    url: str,
    js_fallback: JSFallbackFetcher | None = None,
) -> PageFetchResult:
    result: FetchResult = fetch_engine.fetch(url)
    if not result.ok:
        return PageFetchResult(
            ok=False, http_status=result.http_status, final_url=result.final_url,
            html=None, error=result.error, blocked=result.blocked,
        )

    html = result.content or ""
    if _looks_thin(html):
        renderer = js_fallback or UnavailableJSFallbackFetcher()
        rendered = renderer.render(url)
        if rendered:
            return PageFetchResult(
                ok=True, http_status=result.http_status, final_url=result.final_url,
                html=rendered, error=None, blocked=False, js_fallback_used=True,
                js_fallback_available=True,
            )
        return PageFetchResult(
            ok=True, http_status=result.http_status, final_url=result.final_url,
            html=html, error="js_fallback_required_but_unavailable", blocked=False,
            js_fallback_available=False,
        )

    return PageFetchResult(
        ok=True, http_status=result.http_status, final_url=result.final_url,
        html=html, error=None, blocked=False,
    )


def _looks_thin(html: str) -> bool:
    if not html:
        return True
    # Cheap tag-strip rather than a full BeautifulSoup parse, since this is
    # only a pre-check to decide whether the real parser is worth running.
    import re

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return len(text) < THIN_CONTENT_CHAR_THRESHOLD
