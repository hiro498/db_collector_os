"""spec sections 5-6, 26: the `max_pages` safety cap and configurable
rate-limit delay CrawlEngine gained for PHASE 15, and that neither changes
default (uncapped) crawler behavior for any existing caller.
"""
from __future__ import annotations

import responses

from db_collector_os.competitive_intelligence.crawler import CrawlEngine

_BASE = "https://cap-fixture.example"


def _html(i: int, n: int) -> str:
    links = "".join(f'<a href="{_BASE}/page{j}.html">l{j}</a>' for j in range(n) if j != i)
    return f"<!doctype html><html><head><title>P{i}</title></head><body><main><h1>P{i}</h1><p>c{i}</p>{links}</main></body></html>"


def _register(rsps, n: int) -> None:
    rsps.add(responses.GET, f"{_BASE}/robots.txt", status=404)
    rsps.add(responses.GET, f"{_BASE}/sitemap.xml", status=404)
    rsps.add(responses.GET, f"{_BASE}/", body=_html(0, n), content_type="text/html")
    for i in range(n):
        rsps.add(responses.GET, f"{_BASE}/page{i}.html", body=_html(i, n), content_type="text/html")


def test_max_pages_stops_the_crawl_early(db):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register(rsps, 30)
        engine = CrawlEngine(db, user_agent="Test/1.0", rate_limit_delay_seconds=0.0)
        run_id = engine.start_affiliate_domain(f"{_BASE}/", requested_mode="affiliate_domain", max_pages=10)

    run = db.query_one("SELECT * FROM ci_crawl_runs WHERE crawl_run_id=?", (run_id,))
    page_count = db.query_one("SELECT COUNT(*) AS n FROM ci_pages WHERE crawl_run_id=?", (run_id,))["n"]
    assert page_count == 10
    assert run["status"] == "stopped"
    assert run["converged"] == 0
    assert run["error_message"] == "max_pages_limit_reached"


def test_max_pages_none_preserves_existing_uncapped_behavior(db):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register(rsps, 15)
        engine = CrawlEngine(db, user_agent="Test/1.0", rate_limit_delay_seconds=0.0)
        run_id = engine.start_affiliate_domain(f"{_BASE}/", requested_mode="affiliate_domain")

    run = db.query_one("SELECT * FROM ci_crawl_runs WHERE crawl_run_id=?", (run_id,))
    page_count = db.query_one("SELECT COUNT(*) AS n FROM ci_pages WHERE crawl_run_id=?", (run_id,))["n"]
    assert page_count == 16  # root + 15 distinct pages
    assert run["status"] == "completed"
    assert run["converged"] == 1


def test_max_pages_larger_than_site_completes_normally(db):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register(rsps, 5)
        engine = CrawlEngine(db, user_agent="Test/1.0", rate_limit_delay_seconds=0.0)
        run_id = engine.start_affiliate_domain(f"{_BASE}/", requested_mode="affiliate_domain", max_pages=1000)

    run = db.query_one("SELECT * FROM ci_crawl_runs WHERE crawl_run_id=?", (run_id,))
    assert run["status"] == "completed"
    assert run["converged"] == 1


def test_resume_continues_past_a_max_pages_cap(db):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register(rsps, 20)
        engine = CrawlEngine(db, user_agent="Test/1.0", rate_limit_delay_seconds=0.0)
        run_id = engine.start_affiliate_domain(f"{_BASE}/", requested_mode="affiliate_domain", max_pages=5)
    first_count = db.query_one("SELECT COUNT(*) AS n FROM ci_pages WHERE crawl_run_id=?", (run_id,))["n"]
    assert first_count == 5

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register(rsps, 20)
        engine2 = CrawlEngine(db, user_agent="Test/1.0", rate_limit_delay_seconds=0.0)
        engine2.resume(run_id, max_pages=100)
    second_count = db.query_one("SELECT COUNT(*) AS n FROM ci_pages WHERE crawl_run_id=?", (run_id,))["n"]
    assert second_count > first_count
    run = db.query_one("SELECT * FROM ci_crawl_runs WHERE crawl_run_id=?", (run_id,))
    assert run["status"] == "completed"


def test_rate_limit_delay_seconds_is_configurable_and_defaults_unchanged(db):
    default_engine = CrawlEngine(db, user_agent="Test/1.0")
    assert default_engine.rate_limit_delay_seconds == 1.0
    custom_engine = CrawlEngine(db, user_agent="Test/1.0", rate_limit_delay_seconds=0.001)
    assert custom_engine.rate_limit_delay_seconds == 0.001
