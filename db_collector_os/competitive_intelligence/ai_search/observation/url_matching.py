"""Matches a citation/result URL against this codebase's own crawled pages
(spec section 13). Reuses the exact same normalization the crawler itself
uses (fragment/tracking-param/trailing-slash handling) rather than a
second implementation, so a citation URL and a crawled ``ci_pages.url``
collapse to the same key if and only if the crawler would already treat
them as the same page.
"""

from __future__ import annotations

from ...url_tools import normalize_url
from ....database import Database


def normalize_citation_url(url: str) -> str:
    return normalize_url(url)


def match_page_by_url(db: Database, crawl_run_id: str, url: str) -> dict | None:
    """Finds the ci_pages row (within one crawl_run) whose normalized_url
    matches `url`, or None if no crawled page corresponds to it -- a
    citation pointing at a competitor's page is a completely ordinary,
    expected outcome, not an error.
    """
    normalized = normalize_citation_url(url)
    return db.query_one(
        "SELECT * FROM ci_pages WHERE crawl_run_id=? AND normalized_url=?",
        (crawl_run_id, normalized),
    )
