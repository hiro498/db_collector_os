"""Tests for the Good Smile "Scale Figure Reference List" as a Phase 1
discovery entry point: list-vs-detail page classification, product URL
extraction/dedup via the product_url_pattern filter, pagination-hub
following, and resilience to malformed/empty list pages.

Fixtures are reconstructions (see their own header comments) -- this
environment has no outbound web access to www.goodsmile.com; see
docs/first_production_db.md "Phase 1 discovery method".
"""

from __future__ import annotations

from pathlib import Path

from db_collector_os.adapters import get_adapter
from db_collector_os.candidates import CandidateStore
from db_collector_os.discovery.engine import DiscoveryEngine
from db_collector_os.discovery.search_provider import NullSearchProvider
from db_collector_os.extraction.common import extract_common
from db_collector_os.fetching.client import FetchEngine

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOODSMILE_PATTERN = r"/en/product/(\d+)/|/en/scalefigure_list"
LIST_URL = "https://www.goodsmile.com/en/scalefigure_list"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _job(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "category": "figure",
        "collector_type": "official_site",
        "config_json": {
            "discovery": {
                "internal_links": True,
                "related_entities": False,
                "allowed_domains": ["www.goodsmile.com"],
                "product_url_pattern": GOODSMILE_PATTERN,
            }
        },
    }


def test_list_page_classified_as_skip_not_review():
    html = load_fixture("goodsmile_scalefigure_list.html")
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, LIST_URL)
    record = adapter.extract(common, LIST_URL, html)
    assert record.skip is True
    assert not record.missing_required


def test_product_links_extracted_and_scoped_to_product_pattern(db, job_id):
    html = load_fixture("goodsmile_scalefigure_list.html")
    common = extract_common(html, LIST_URL)

    candidates = CandidateStore(db)
    fetch_engine = FetchEngine(user_agent="TestBot/1.0", respect_robots=False)
    engine = DiscoveryEngine(fetch_engine, candidates, NullSearchProvider())
    engine.discover_from_page(_job(job_id), common, "www.goodsmile.com")

    rows = db.query("SELECT url FROM entity_candidates WHERE job_id=? ORDER BY url", (job_id,))
    urls = [r["url"] for r in rows]

    # off-domain and non-product/non-list links (about/contact/cart/account/search/privacy) excluded:
    assert not any("not-goodsmile" in u for u in urls)
    assert not any("/about" in u or "/contact" in u or "/cart" in u or "/account" in u or "/privacy" in u for u in urls)
    assert not any("/search" in u for u in urls)

    # every real product ID is present exactly once (dedup collapsed the duplicate 1141716 slug):
    product_urls = [u for u in urls if "/product/" in u]
    ids_seen = {u.split("/product/")[1].split("/")[0] for u in product_urls}
    assert ids_seen == {"1141716", "2200481", "3301592", "4402703", "5503814"}
    assert len(product_urls) == 5  # not 6 -- the duplicate 1141716 slug was suppressed

    # the pagination hub link was kept too (no stable_id -> its own URL fingerprint):
    assert any(u == "https://www.goodsmile.com/en/scalefigure_list?page=2" for u in urls)


def test_pagination_page2_also_yields_product_links(db, job_id):
    html = load_fixture("goodsmile_scalefigure_list_page2.html")
    common = extract_common(html, LIST_URL + "?page=2")

    candidates = CandidateStore(db)
    fetch_engine = FetchEngine(user_agent="TestBot/1.0", respect_robots=False)
    engine = DiscoveryEngine(fetch_engine, candidates, NullSearchProvider())
    engine.discover_from_page(_job(job_id), common, "www.goodsmile.com")

    rows = db.query("SELECT url FROM entity_candidates WHERE job_id=?", (job_id,))
    urls = {r["url"] for r in rows}
    assert any("6604925" in u for u in urls)
    assert any("7706036" in u for u in urls)


def test_empty_list_page_yields_no_candidates_and_no_crash(db, job_id):
    html = load_fixture("goodsmile_scalefigure_list_empty.html")
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, LIST_URL)
    record = adapter.extract(common, LIST_URL, html)
    assert record.skip is True

    candidates = CandidateStore(db)
    fetch_engine = FetchEngine(user_agent="TestBot/1.0", respect_robots=False)
    engine = DiscoveryEngine(fetch_engine, candidates, NullSearchProvider())
    found = engine.discover_from_page(_job(job_id), common, "www.goodsmile.com")
    assert found == []
    rows = db.query("SELECT * FROM entity_candidates WHERE job_id=?", (job_id,))
    assert rows == []


def test_malformed_list_page_does_not_crash_and_still_finds_the_product_link(db, job_id):
    html = load_fixture("goodsmile_scalefigure_list_malformed.html")
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, LIST_URL)
    record = adapter.extract(common, LIST_URL, html)
    assert record.skip is True  # malformed ItemList JSON-LD, no valid Product -> still a list page

    candidates = CandidateStore(db)
    fetch_engine = FetchEngine(user_agent="TestBot/1.0", respect_robots=False)
    engine = DiscoveryEngine(fetch_engine, candidates, NullSearchProvider())
    engine.discover_from_page(_job(job_id), common, "www.goodsmile.com")

    rows = db.query("SELECT url FROM entity_candidates WHERE job_id=?", (job_id,))
    assert any("8807147" in r["url"] for r in rows)
