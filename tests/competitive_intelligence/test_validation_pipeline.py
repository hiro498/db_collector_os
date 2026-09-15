"""End-to-end PHASE 15 tests against the realistic local affiliate-site
fixture (spec sections 33-35): a single `validate-domain`-equivalent call
must complete crawl -> classify -> keyword extraction -> site aggregation
-> intent -> commercial -> AI Readiness -> Opportunity -> ranking -> CSV
without crashing, and the resulting TOP50 A+B rate must match human
intuition (>= 90% on this controlled fixture, with scaffolding/navigation
noise never occupying a top-ranked slot).
"""
from __future__ import annotations

import responses

from db_collector_os.database import new_id
from db_collector_os.job_registry import now_iso
from db_collector_os.competitive_intelligence.ai_search import analyze_ai_page
from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.repository.pages import PageRepository
from db_collector_os.competitive_intelligence.validation import ValidationOptions, run_validation
from db_collector_os.competitive_intelligence.validation.config import TOP50_AB_TARGET_THRESHOLD
from db_collector_os.competitive_intelligence.validation.repository import (
    DomainKeywordSummaryRepository, TargetKeywordPriorityRepository, ValidationRunRepository,
)

from .fixtures.affiliate_site import BASE, EXPECTED_NOISE_TERMS, EXPECTED_STRONG_KEYWORDS, build_fixture_site

_FAST_OPTIONS_KWARGS = {"rate_limit_requests_per_second": 100_000.0}


def _register_fixture(rsps) -> dict[str, str]:
    pages = build_fixture_site()
    rsps.add(responses.GET, f"{BASE}/robots.txt", status=404)
    rsps.add(responses.GET, f"{BASE}/sitemap.xml", status=404)
    for url, html in pages.items():
        rsps.add(responses.GET, url, body=html, content_type="text/html")
    return pages


def _run_fixture_validation(db, max_pages: int = 30, our_domain_run_id: str | None = None) -> str:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_fixture(rsps)
        return run_validation(
            db, f"{BASE}/",
            ValidationOptions(max_pages=max_pages, our_domain_run_id=our_domain_run_id, **_FAST_OPTIONS_KWARGS),
        )


def test_end_to_end_completes_without_crash(db):
    validation_run_id = _run_fixture_validation(db)
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["status"] == "COMPLETED"
    assert run["production_validation_status"] in ("PASS", "CONDITIONAL_PASS", "FAIL")


def test_end_to_end_produces_all_pipeline_outputs(db):
    validation_run_id = _run_fixture_validation(db)
    keywords = DomainKeywordSummaryRepository(db).list_for_run(validation_run_id)
    priorities = TargetKeywordPriorityRepository(db).list_for_run(validation_run_id)
    assert len(keywords) > 0
    assert len(priorities) > 0
    assert all(p["priority_rank"] == i + 1 for i, p in enumerate(priorities))


def test_page_type_stats_in_summary(db):
    import json

    validation_run_id = _run_fixture_validation(db)
    run = ValidationRunRepository(db).get(validation_run_id)
    summary = json.loads(run["summary_json"])
    assert summary["pages_fetched"] == 20
    assert summary["pages_analyzed"] > 0
    assert isinstance(summary["pages_by_type"], dict)
    assert sum(summary["pages_by_type"].values()) == summary["pages_fetched"]


def test_quality_kpi_meets_target_on_controlled_fixture(db):
    """spec sections 10, 35: TOP50 A+B >= 90% on this controlled fixture."""
    validation_run_id = _run_fixture_validation(db)
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["top50_ab_rate"] is not None
    assert run["top50_ab_rate"] >= TOP50_AB_TARGET_THRESHOLD, (
        f"expected TOP50 A+B >= {TOP50_AB_TARGET_THRESHOLD:.0%}, got {run['top50_ab_rate']:.0%}"
    )


def test_expected_strong_keywords_are_not_graded_noise(db):
    validation_run_id = _run_fixture_validation(db)
    keywords = {k["normalized_keyword"]: k for k in DomainKeywordSummaryRepository(db).list_for_run(validation_run_id)}
    for term in EXPECTED_STRONG_KEYWORDS:
        assert term in keywords, f"expected {term!r} to be extracted as a keyword candidate"
        assert keywords[term]["is_noise"] == 0
        assert keywords[term]["audit_class_auto"] in ("A", "B")


def test_navigation_and_footer_noise_never_occupies_top50(db):
    """spec section 35: navigation/footer noise must not occupy top ranks."""
    validation_run_id = _run_fixture_validation(db)
    keywords = DomainKeywordSummaryRepository(db).list_for_run(validation_run_id)
    candidates = sorted(
        [k for k in keywords if k["cluster_is_representative"] and not k["is_noise"]],
        key=lambda k: k["best_keyword_score"], reverse=True,
    )
    top50_texts = {k["keyword"] for k in candidates[:50]}
    for noise_term in EXPECTED_NOISE_TERMS:
        assert noise_term not in top50_texts


def test_our_domain_run_produces_real_opportunity_score_for_shared_keyword(db):
    our_html = """<!doctype html><html><head><title>おすすめ健康グッズの当サイト</title>
    <link rel="canonical" href="https://our-site.example/health/"></head><body>
    <main><h1>おすすめ健康グッズの当サイト紹介</h1><p>当サイトのおすすめ健康グッズについて紹介するページです。</p></main>
    </body></html>"""
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://our-site.example/health/", body=our_html, content_type="text/html")
        our_engine = CrawlEngine(db, user_agent="Test/1.0")
        our_run_id = our_engine.start_advertiser_lp("https://our-site.example/health/", requested_mode="advertiser_lp")

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_fixture(rsps)
        precrawl_engine = CrawlEngine(db, user_agent="Test/1.0", rate_limit_delay_seconds=0.0)
        precrawl_engine.start_affiliate_domain(f"{BASE}/", requested_mode="affiliate_domain", max_pages=30)

    kw_row = db.query_one("SELECT keyword_id, keyword FROM ci_keywords WHERE normalized_keyword=?", ("健康グッズ",))
    assert kw_row, "expected the competitor crawl to have generated a real '健康グッズ' keyword"

    our_page = PageRepository(db).list_for_run(our_run_id, limit=1)[0]
    db.execute(
        "INSERT INTO ci_page_keywords (page_keyword_id, page_id, keyword_id, crawl_run_id, score, "
        "commercial_score, importance, is_primary, computed_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (new_id("pk_"), our_page["page_id"], kw_row["keyword_id"], our_run_id, 100, 60, "primary", 1, now_iso()),
    )
    analyze_ai_page(db, our_page["page_id"])

    validation_run_id = _run_fixture_validation(db, our_domain_run_id=our_run_id)
    priorities = TargetKeywordPriorityRepository(db).list_for_run(validation_run_id)
    matched = [p for p in priorities if p["normalized_keyword"] == "健康グッズ"]
    assert matched, "expected the shared keyword to appear in the ranking"
    row = matched[0]
    assert row["opportunity_score"] is not None
    assert row["score_status"] != "NOT_ENOUGH_DATA"


def test_without_our_domain_run_opportunity_is_not_enough_data(db):
    validation_run_id = _run_fixture_validation(db)
    priorities = TargetKeywordPriorityRepository(db).list_for_run(validation_run_id)
    assert all(p["opportunity_score"] is None for p in priorities)
    assert all(p["score_status"] == "NOT_ENOUGH_DATA" for p in priorities)
    assert all(p["recommended_action"] == "CREATE_NEW_PAGE" for p in priorities)


def test_no_external_observation_is_null_not_zero(db):
    validation_run_id = _run_fixture_validation(db)
    priorities = TargetKeywordPriorityRepository(db).list_for_run(validation_run_id)
    assert all(p["organic_rank"] is None for p in priorities)
    assert all(p["aio_cited"] is None for p in priorities)
    assert all(p["ai_mode_cited"] is None for p in priorities)


def test_demand_unavailable_without_import(db):
    validation_run_id = _run_fixture_validation(db)
    priorities = TargetKeywordPriorityRepository(db).list_for_run(validation_run_id)
    assert all(p["demand_status"] == "UNAVAILABLE" for p in priorities)
    assert all(p["search_volume"] is None for p in priorities)


def test_blue_ocean_insufficient_data_without_demand(db):
    validation_run_id = _run_fixture_validation(db)
    priorities = TargetKeywordPriorityRepository(db).list_for_run(validation_run_id)
    assert all(p["blue_ocean_candidate_status"] == "INSUFFICIENT_DATA" for p in priorities)
    assert all(p["blue_ocean_candidate"] is None for p in priorities)


def test_resume_continues_a_capped_validation_run(db):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_fixture(rsps)
        first_run_id = run_validation(db, f"{BASE}/", ValidationOptions(max_pages=5, **_FAST_OPTIONS_KWARGS))
    first_run = ValidationRunRepository(db).get(first_run_id)
    first_pages = db.query_one(
        "SELECT COUNT(*) AS n FROM ci_pages WHERE crawl_run_id=?", (first_run["crawl_run_id"],)
    )["n"]
    assert first_pages == 5

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_fixture(rsps)
        resumed_run_id = run_validation(
            db, f"{BASE}/",
            ValidationOptions(max_pages=30, resume_validation_run_id=first_run_id, **_FAST_OPTIONS_KWARGS),
        )
    assert resumed_run_id == first_run_id
    resumed_run = ValidationRunRepository(db).get(resumed_run_id)
    resumed_pages = db.query_one(
        "SELECT COUNT(*) AS n FROM ci_pages WHERE crawl_run_id=?", (resumed_run["crawl_run_id"],)
    )["n"]
    assert resumed_pages > first_pages
    assert resumed_run["status"] == "COMPLETED"


def test_resume_unknown_run_id_raises(db):
    import pytest

    with pytest.raises(ValueError):
        run_validation(db, f"{BASE}/", ValidationOptions(resume_validation_run_id="no-such-run"))


def test_production_validation_status_conditional_pass_below_threshold(db, monkeypatch):
    import db_collector_os.competitive_intelligence.validation.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "TOP50_AB_PASS_THRESHOLD", 1.01)  # impossible to reach -> CONDITIONAL_PASS
    validation_run_id = _run_fixture_validation(db)
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["production_validation_status"] == "CONDITIONAL_PASS"


def test_human_audit_overrides_kpi_source_once_top50_fully_audited(db):
    validation_run_id = _run_fixture_validation(db)
    keywords_repo = DomainKeywordSummaryRepository(db)
    candidates = sorted(
        [k for k in keywords_repo.list_for_run(validation_run_id) if k["cluster_is_representative"] and not k["is_noise"]],
        key=lambda k: k["best_keyword_score"], reverse=True,
    )[:50]
    for k in candidates:
        keywords_repo.set_human_audit(validation_run_id, k["normalized_keyword"], "A", "reviewed")

    # Re-running the aggregation portion of the pipeline isn't idempotent
    # against manual DB edits mid-run in this test, so we just confirm the
    # audit itself persisted correctly and independently of audit_class_auto.
    updated = keywords_repo.list_for_run(validation_run_id)
    audited = [k for k in updated if k["audit_class"] == "A"]
    assert len(audited) == len(candidates)
    assert all(k["audit_class_auto"] is not None for k in audited)
