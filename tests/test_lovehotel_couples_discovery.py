"""Discovery tests for the Couples area-listing page as a Phase 1 entry
point: facility-link extraction, tracking-param dedup, pagination
following, and resilience to an empty/malformed list page.

Unlike the Good Smile figure job, this job's `discovery.internal_links` is
deliberately left UNSCOPED by any facility-URL regex (no
`discovery.product_url_pattern` in config/jobs/prod_lovehotel_couples.yaml)
-- this authoring environment cannot verify couples.jp's real URL scheme
(see docs/lovehotel_couples_db.md), so restricting internal_links to a
guessed pattern risks silently excluding the very prefecture/area listing
pages a nationwide crawl needs to traverse to reach facility pages at all.
Classification of "is this actually a facility" is left entirely to the
adapter's own skip logic (see test_lovehotel_couples_adapter.py), not to
URL-shape filtering. This module only tests that internal-link discovery
itself is correctly scoped to the couples.jp domain and dedupes normalized
URLs, which is domain-agnostic infrastructure already used by every other
adapter in this repo.
"""

from __future__ import annotations

from pathlib import Path

from db_collector_os.candidates import CandidateStore
from db_collector_os.discovery.engine import DiscoveryEngine
from db_collector_os.discovery.search_provider import NullSearchProvider
from db_collector_os.extraction.common import extract_common
from db_collector_os.fetching.client import FetchEngine

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _job(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "category": "love_hotel",
        "collector_type": "local_business",
        "config_json": {
            "discovery": {
                "internal_links": True,
                "related_entities": False,
                "allowed_domains": ["couples.jp"],
            }
        },
    }


def _engine(db) -> DiscoveryEngine:
    fetch_engine = FetchEngine(user_agent="TestBot/1.0", respect_robots=False)
    return DiscoveryEngine(fetch_engine, CandidateStore(db), NullSearchProvider())


def test_area_list_facility_links_discovered_and_scoped_to_domain(db, job_id):
    html = load_fixture("couples_area_list.html")
    common = extract_common(html, "https://couples.jp/tokyo/")

    engine = _engine(db)
    engine.discover_from_page(_job(job_id), common, "couples.jp")

    rows = db.query("SELECT url FROM entity_candidates WHERE job_id=? ORDER BY url", (job_id,))
    urls = [r["url"] for r in rows]

    assert any("hotel/12345" in u for u in urls)
    assert any("hotel/23456" in u for u in urls)
    assert any("hotel/34567" in u for u in urls)
    assert any("hotel/45678" in u for u in urls)

    # the "next page" pagination link is a normal same-domain link -- kept
    # (normalize_url() strips the trailing slash before the query string):
    assert any(u == "https://couples.jp/tokyo?page=2" for u in urls)

    # off-domain link excluded even though it looks like a facility URL:
    assert not any("not-couples.example.com" in u for u in urls)

    # nav/footer non-facility links are still on-domain and therefore
    # discovered too (this job scopes by domain, not URL shape -- see
    # module docstring); they will be classified and dropped by the
    # adapter's own skip logic once actually fetched, not filtered here.
    assert any("/privacy" in u for u in urls)


def test_duplicate_facility_link_with_tracking_param_normalizes_to_one_candidate(db, job_id):
    """The list page links to hotel/12345 twice: once plain, once with a
    utm_source tracking param. normalize_url() strips known tracking params,
    so both must collapse to exactly one entity_candidate row, not two."""
    html = load_fixture("couples_area_list.html")
    common = extract_common(html, "https://couples.jp/tokyo/")

    engine = _engine(db)
    engine.discover_from_page(_job(job_id), common, "couples.jp")

    rows = db.query(
        "SELECT url FROM entity_candidates WHERE job_id=? AND url LIKE '%hotel/12345%'", (job_id,)
    )
    assert len(rows) == 1


def test_pagination_page2_yields_further_facility_links(db, job_id):
    html = load_fixture("couples_area_list_page2.html")
    common = extract_common(html, "https://couples.jp/tokyo/?page=2")

    engine = _engine(db)
    engine.discover_from_page(_job(job_id), common, "couples.jp")

    rows = db.query("SELECT url FROM entity_candidates WHERE job_id=?", (job_id,))
    urls = {r["url"] for r in rows}
    assert any("hotel/56789" in u for u in urls)
    assert any("hotel/67890" in u for u in urls)


def test_empty_area_list_yields_no_candidates_and_no_crash(db, job_id):
    html = load_fixture("couples_area_list_empty.html")
    common = extract_common(html, "https://couples.jp/okinawa/")

    engine = _engine(db)
    found = engine.discover_from_page(_job(job_id), common, "couples.jp")
    assert found == []

    rows = db.query("SELECT * FROM entity_candidates WHERE job_id=?", (job_id,))
    assert rows == []


def test_malformed_page_discovery_does_not_crash():
    html = load_fixture("couples_malformed.html")
    common = extract_common(html, "https://couples.jp/error-page")  # must not raise
    assert common["links"] == [] or isinstance(common["links"], list)


def test_repeated_discovery_calls_do_not_grow_fetch_queue_unboundedly(db, job_id):
    """Same page discovered twice (e.g. re-fetched on a later run) must not
    keep adding new entity_candidates rows for URLs already known -- see
    STEP 4 of docs/lovehotel_couples_db.md ('同一施設URLを何度発見しても
    fetch queueを無限増殖させない')."""
    html = load_fixture("couples_area_list.html")
    common = extract_common(html, "https://couples.jp/tokyo/")
    engine = _engine(db)

    first = engine.discover_from_page(_job(job_id), common, "couples.jp")
    second = engine.discover_from_page(_job(job_id), common, "couples.jp")

    assert len(first) > 0
    assert second == []  # nothing genuinely new the second time
    total_rows = db.query_one("SELECT COUNT(*) AS n FROM entity_candidates WHERE job_id=?", (job_id,))
    assert total_rows["n"] == len(first)
