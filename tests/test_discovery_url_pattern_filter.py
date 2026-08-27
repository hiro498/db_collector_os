"""Tests for the product-URL-pattern filter added to internal_links
discovery (used by Phase 1 batch #1 to keep the fetch queue scoped to real
product detail links + list/pagination hubs, filtering out unrelated
same-domain pages like about/contact/cart -- and to /search, which
robots.txt disallows) and the stable-id-based candidate dedup it enables.
"""

from __future__ import annotations

from db_collector_os.candidates import CandidateStore
from db_collector_os.discovery.internal_links import discover_internal_links
from db_collector_os.discovery.engine import DiscoveryEngine
from db_collector_os.discovery.search_provider import NullSearchProvider
from db_collector_os.fetching.client import FetchEngine

GOODSMILE_PATTERN = r"/en/product/(\d+)/|/en/scalefigure_list"


def test_no_pattern_keeps_all_same_domain_links_unchanged():
    links = [
        "https://www.goodsmile.com/en/product/1141716/x",
        "https://www.goodsmile.com/en/about",
        "https://other.example.com/en/product/999/y",
    ]
    found = discover_internal_links(links, "www.goodsmile.com", {"www.goodsmile.com"})
    assert {f.url for f in found} == {
        "https://www.goodsmile.com/en/product/1141716/x",
        "https://www.goodsmile.com/en/about",
    }


def test_pattern_keeps_only_product_and_list_links():
    links = [
        "https://www.goodsmile.com/en/product/1141716/rikka-akane",
        "https://www.goodsmile.com/en/scalefigure_list?page=2",
        "https://www.goodsmile.com/en/about",
        "https://www.goodsmile.com/en/contact",
        "https://www.goodsmile.com/en/cart",
        "https://www.goodsmile.com/account",
    ]
    found = discover_internal_links(links, "www.goodsmile.com", {"www.goodsmile.com"}, GOODSMILE_PATTERN)
    urls = {f.url for f in found}
    assert urls == {
        "https://www.goodsmile.com/en/product/1141716/rikka-akane",
        "https://www.goodsmile.com/en/scalefigure_list?page=2",
    }


def test_foreign_domain_excluded_even_if_url_matches_pattern():
    links = ["https://not-goodsmile.example.com/en/product/1141716/fake"]
    found = discover_internal_links(links, "www.goodsmile.com", {"www.goodsmile.com"}, GOODSMILE_PATTERN)
    assert found == []


def test_search_path_never_passes_the_product_pattern_filter():
    """robots.txt disallows /*/search -- confirm our own filter would never
    hand a /search URL to the fetch queue even if one were linked somewhere.
    """
    links = ["https://www.goodsmile.com/en/search?q=figure"]
    found = discover_internal_links(links, "www.goodsmile.com", {"www.goodsmile.com"}, GOODSMILE_PATTERN)
    assert found == []


def test_stable_id_extracted_from_matched_product_url():
    links = ["https://www.goodsmile.com/en/product/1141716/rikka-akane"]
    found = discover_internal_links(links, "www.goodsmile.com", {"www.goodsmile.com"}, GOODSMILE_PATTERN)
    assert len(found) == 1
    assert found[0].stable_id == "1141716"


def test_list_page_link_has_no_stable_id():
    links = ["https://www.goodsmile.com/en/scalefigure_list?page=2"]
    found = discover_internal_links(links, "www.goodsmile.com", {"www.goodsmile.com"}, GOODSMILE_PATTERN)
    assert len(found) == 1
    assert found[0].stable_id is None


def test_no_product_links_on_page_yields_empty_list():
    links = ["https://www.goodsmile.com/en/about", "https://www.goodsmile.com/en/contact"]
    found = discover_internal_links(links, "www.goodsmile.com", {"www.goodsmile.com"}, GOODSMILE_PATTERN)
    assert found == []


def test_engine_dedups_candidates_by_stable_id_across_different_urls(db, job_id):
    """Two different URLs (different slug) for the same numeric product ID
    must collapse into a single entity_candidate row.
    """
    candidates = CandidateStore(db)
    fetch_engine = FetchEngine(user_agent="TestBot/1.0", respect_robots=False)
    engine = DiscoveryEngine(fetch_engine, candidates, NullSearchProvider())

    job = {
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
    extracted = {
        "links": [
            "https://www.goodsmile.com/en/product/1141716/rikka-akane",
            "https://www.goodsmile.com/en/product/1141716/alternate-slug",
        ],
        "json_ld": [],
    }
    engine.discover_from_page(job, extracted, "www.goodsmile.com")

    rows = db.query("SELECT * FROM entity_candidates WHERE job_id=?", (job_id,))
    assert len(rows) == 1
    assert rows[0]["url"] == "https://www.goodsmile.com/en/product/1141716/rikka-akane"


def test_engine_falls_back_to_url_fingerprint_when_no_stable_id(db, job_id):
    candidates = CandidateStore(db)
    fetch_engine = FetchEngine(user_agent="TestBot/1.0", respect_robots=False)
    engine = DiscoveryEngine(fetch_engine, candidates, NullSearchProvider())

    job = {
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
    extracted = {
        "links": [
            "https://www.goodsmile.com/en/scalefigure_list?page=2",
            "https://www.goodsmile.com/en/scalefigure_list?page=3",
        ],
        "json_ld": [],
    }
    engine.discover_from_page(job, extracted, "www.goodsmile.com")

    rows = db.query("SELECT * FROM entity_candidates WHERE job_id=?", (job_id,))
    assert len(rows) == 2  # distinct URLs, no stable_id -> not collapsed
