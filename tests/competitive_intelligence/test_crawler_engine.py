from __future__ import annotations

from pathlib import Path

import responses

from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.enums import CrawlRunStatus, CrawlUrlStatus, ExclusionReason
from db_collector_os.competitive_intelligence.repository.core import CrawlRunRepository, CrawlUrlRepository
from db_collector_os.competitive_intelligence.repository.pages import PageRepository

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _mock_site():
    responses.add(responses.GET, "https://example.jp/robots.txt", status=404)
    responses.add(responses.GET, "https://example.jp/sitemap.xml", status=404)
    responses.add(responses.GET, "https://example.jp/", body=_read("top.html"), content_type="text/html")
    responses.add(responses.GET, "https://example.jp/ramen-ranking/", body=_read("ranking.html"),
                  content_type="text/html")
    responses.add(responses.GET, "https://example.jp/ramen-ranking/?page=2", body=_read("ranking_page2.html"),
                  content_type="text/html")
    responses.add(responses.GET, "https://example.jp/company/", body=_read("company.html"), content_type="text/html")
    responses.add(responses.GET, "https://example.jp/privacy/", body=_read("privacy_noindex.html"),
                  content_type="text/html")


@responses.activate
def test_affiliate_domain_crawl_converges_and_excludes_out_of_scope_urls(db):
    _mock_site()
    engine = CrawlEngine(db, user_agent="TestBot/1.0")
    run_id = engine.start_affiliate_domain("https://example.jp/", requested_mode="affiliate_domain")

    run = CrawlRunRepository(db).get(run_id)
    assert run["status"] == CrawlRunStatus.COMPLETED
    assert run["converged"] == 1
    assert run["unresolved_count"] == 0

    urls = {u["url"]: u for u in CrawlUrlRepository(db).list_all(run_id, limit=100)}

    # in-scope pages were fetched and completed
    assert urls["https://example.jp/"]["status"] == CrawlUrlStatus.COMPLETED
    assert urls["https://example.jp/ramen-ranking/"]["status"] == CrawlUrlStatus.COMPLETED
    assert urls["https://example.jp/company/"]["status"] == CrawlUrlStatus.COMPLETED

    # subdomain / external domain / asset / mailto never fetched, but recorded
    assert urls["https://sub.example.jp/other/"]["status"] == CrawlUrlStatus.EXCLUDED
    assert urls["https://sub.example.jp/other/"]["exclusion_reason"] == ExclusionReason.SUBDOMAIN
    assert urls["https://external.example.com/"]["exclusion_reason"] == ExclusionReason.EXTERNAL_DOMAIN
    assert urls["https://example.jp/logo.png"]["exclusion_reason"] == ExclusionReason.NON_HTML_ASSET
    assert urls["mailto:info@example.jp"]["exclusion_reason"] == ExclusionReason.MAILTO


@responses.activate
def test_pagination_and_canonical_duplicate_detection(db):
    _mock_site()
    engine = CrawlEngine(db, user_agent="TestBot/1.0")
    run_id = engine.start_affiliate_domain("https://example.jp/", requested_mode="affiliate_domain")

    page2 = CrawlUrlRepository(db).get_by_normalized(run_id, "https://example.jp/ramen-ranking?page=2")
    assert page2["is_pagination"] == 1
    assert page2["is_canonical_duplicate"] == 1
    assert page2["analysis_target"] == 0

    page2_row = PageRepository(db).get_by_crawl_url(page2["crawl_url_id"])
    assert page2_row["analysis_target"] == 0


@responses.activate
def test_noindex_page_is_recorded_but_excluded_from_analysis(db):
    _mock_site()
    engine = CrawlEngine(db, user_agent="TestBot/1.0")
    run_id = engine.start_affiliate_domain("https://example.jp/", requested_mode="affiliate_domain")

    privacy_url = CrawlUrlRepository(db).get_by_normalized(run_id, "https://example.jp/privacy")
    assert privacy_url["status"] == CrawlUrlStatus.COMPLETED  # crawled/recorded
    assert privacy_url["analysis_target"] == 0  # but excluded from SEO/KW aggregation

    page = PageRepository(db).get_by_crawl_url(privacy_url["crawl_url_id"])
    assert "noindex" in (page["robots_meta"] or "")
    assert page["analysis_target"] == 0

    run = CrawlRunRepository(db).get(run_id)
    assert run["noindex_count"] >= 1


@responses.activate
def test_company_page_excluded_from_analysis_target(db):
    _mock_site()
    engine = CrawlEngine(db, user_agent="TestBot/1.0")
    run_id = engine.start_affiliate_domain("https://example.jp/", requested_mode="affiliate_domain")

    pages = {p["url"]: p for p in PageRepository(db).list_for_run(run_id, limit=100)}
    assert pages["https://example.jp/company/"]["page_type"] == "company"
    assert pages["https://example.jp/company/"]["analysis_target"] == 0
    assert pages["https://example.jp/ramen-ranking/"]["analysis_target"] == 1


@responses.activate
def test_advertiser_lp_mode_never_crawls_the_domain(db):
    responses.add(responses.GET, "https://example.jp/ramen-ranking/", body=_read("ranking.html"),
                  content_type="text/html")
    engine = CrawlEngine(db, user_agent="TestBot/1.0")
    run_id = engine.start_advertiser_lp("https://example.jp/ramen-ranking/", requested_mode="advertiser_lp")

    urls = CrawlUrlRepository(db).list_all(run_id, limit=100)
    assert len(urls) == 1  # no internal-link discovery in advertiser_lp mode
    run = CrawlRunRepository(db).get(run_id)
    assert run["status"] == CrawlRunStatus.COMPLETED


@responses.activate
def test_stop_request_halts_crawl_without_losing_progress_and_resume_continues(db):
    _mock_site()
    engine = CrawlEngine(db, user_agent="TestBot/1.0")

    # Seed a run and stop it before any URL is processed by requesting stop
    # first, then starting -- start_affiliate_domain's own loop checks
    # stop_requested at the very first iteration boundary.
    from db_collector_os.competitive_intelligence.repository.core import DomainRepository
    from db_collector_os.competitive_intelligence.url_tools import extract_host, normalize_url

    normalized = normalize_url("https://example.jp/")
    host = extract_host(normalized)
    domain = DomainRepository(db).get_or_create(host, target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(domain["domain_id"], "https://example.jp/", "affiliate_domain",
                                            "affiliate_domain", "general")
    CrawlUrlRepository(db).add(run_id, domain["domain_id"], "https://example.jp/", normalized, discovered_by="seed")
    CrawlRunRepository(db).request_stop(run_id)

    engine._drain(run_id, host, single_page=False)
    run = CrawlRunRepository(db).get(run_id)
    assert run["status"] == CrawlRunStatus.STOPPED
    # the seed URL was never fetched -- stop was honored before processing it
    assert CrawlUrlRepository(db).get_by_normalized(run_id, normalized)["status"] == CrawlUrlStatus.DISCOVERED

    # resume() clears stop_requested and completes the crawl without error
    resumed_id = engine.resume(run_id)
    assert resumed_id == run_id
    run = CrawlRunRepository(db).get(run_id)
    assert run["status"] == CrawlRunStatus.COMPLETED
    assert run["stop_requested"] == 0


@responses.activate
def test_resume_never_refetches_a_completed_url(db):
    """A crawl_url already `completed` must not be requested again on
    resume -- only truly pending URLs get (re)fetched."""
    from db_collector_os.competitive_intelligence.repository.core import DomainRepository
    from db_collector_os.competitive_intelligence.url_tools import extract_host, normalize_url

    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(domain["domain_id"], "https://example.jp/", "affiliate_domain",
                                            "affiliate_domain", "general")
    completed_url = normalize_url("https://example.jp/already-done/")
    pending_url = normalize_url("https://example.jp/company/")
    crawl_url_repo = CrawlUrlRepository(db)
    completed_id, _ = crawl_url_repo.add(run_id, domain["domain_id"], "https://example.jp/already-done/",
                                          completed_url, discovered_by="seed")
    crawl_url_repo.set_status(completed_id, CrawlUrlStatus.COMPLETED)
    crawl_url_repo.add(run_id, domain["domain_id"], "https://example.jp/company/", pending_url,
                        discovered_by="internal_link")

    # Only the pending URL is mocked; if the engine tried to refetch the
    # completed one, responses would raise ConnectionError for the
    # unregistered https://example.jp/already-done/ request.
    responses.add(responses.GET, "https://example.jp/company/", body=_read("company.html"), content_type="text/html")

    engine = CrawlEngine(db, user_agent="TestBot/1.0")
    engine._drain(run_id, "example.jp", single_page=False)

    assert crawl_url_repo.get(completed_id)["status"] == CrawlUrlStatus.COMPLETED
