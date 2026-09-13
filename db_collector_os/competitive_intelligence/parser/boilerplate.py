"""Boilerplate detection (spec section 15).

Two passes, both marking `is_boilerplate=1` rather than deleting anything:

1. Structural containers (nav/header/footer/cookie_notice) are always
   boilerplate -- the parser already tags them with those element_types.
2. Any other (element_type, text) pair repeated near-identically across a
   large share of the crawl_run's pages is a template-candidate (a common
   CTA block, a repeated notice, a shared sidebar list, ...).
"""

from __future__ import annotations

from ...database import Database

_ALWAYS_BOILERPLATE_TYPES = ("nav", "header", "footer", "cookie_notice")

DEFAULT_MIN_PAGES = 3
DEFAULT_RATIO_THRESHOLD = 0.6


def detect_and_mark_boilerplate(
    db: Database,
    crawl_run_id: str,
    min_pages: int = DEFAULT_MIN_PAGES,
    ratio_threshold: float = DEFAULT_RATIO_THRESHOLD,
) -> int:
    marked = 0
    placeholders = ",".join("?" for _ in _ALWAYS_BOILERPLATE_TYPES)
    rows = db.query(
        f"SELECT pe.page_element_id FROM ci_page_elements pe JOIN ci_pages p ON p.page_id = pe.page_id "
        f"WHERE p.crawl_run_id=? AND pe.element_type IN ({placeholders}) AND pe.is_boilerplate=0",
        (crawl_run_id, *_ALWAYS_BOILERPLATE_TYPES),
    )
    ids = [r["page_element_id"] for r in rows]
    if ids:
        _mark(db, ids)
        marked += len(ids)

    total_pages_row = db.query_one("SELECT COUNT(*) AS n FROM ci_pages WHERE crawl_run_id=?", (crawl_run_id,))
    total_pages = total_pages_row["n"] if total_pages_row else 0
    if total_pages < min_pages:
        return marked

    repeated = db.query(
        "SELECT pe.element_type, pe.text, COUNT(DISTINCT pe.page_id) AS page_count "
        "FROM ci_page_elements pe JOIN ci_pages p ON p.page_id = pe.page_id "
        "WHERE p.crawl_run_id=? AND pe.text IS NOT NULL AND pe.is_boilerplate=0 "
        "GROUP BY pe.element_type, pe.text HAVING COUNT(DISTINCT pe.page_id) >= ?",
        (crawl_run_id, min_pages),
    )
    for row in repeated:
        if row["page_count"] / total_pages < ratio_threshold:
            continue
        matches = db.query(
            "SELECT pe.page_element_id FROM ci_page_elements pe JOIN ci_pages p ON p.page_id = pe.page_id "
            "WHERE p.crawl_run_id=? AND pe.element_type=? AND pe.text=? AND pe.is_boilerplate=0",
            (crawl_run_id, row["element_type"], row["text"]),
        )
        ids = [m["page_element_id"] for m in matches]
        if ids:
            _mark(db, ids)
            marked += len(ids)
    return marked


def _mark(db: Database, page_element_ids: list[int]) -> None:
    placeholders = ",".join("?" for _ in page_element_ids)
    db.execute(
        f"UPDATE ci_page_elements SET is_boilerplate=1 WHERE page_element_id IN ({placeholders})",
        page_element_ids,
    )
