from __future__ import annotations

from db_collector_os.competitive_intelligence.opportunity.repository import (
    ComparisonRepository, ContentGapRepository, KeywordMetricsRepository, OpportunityRepository,
)
from db_collector_os.competitive_intelligence.repository.core import (
    CrawlRunRepository, CrawlUrlRepository, DomainRepository,
)
from db_collector_os.competitive_intelligence.repository.pages import PageRepository


_SEED_COUNTER = {"n": 0}


def _seed_page(db) -> tuple[str, str]:
    _SEED_COUNTER["n"] += 1
    path = f"/a{_SEED_COUNTER['n']}"
    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(
        domain["domain_id"], "https://example.jp/", "affiliate_domain", "affiliate_domain", "general",
    )
    crawl_url_id, _ = CrawlUrlRepository(db).add(
        run_id, domain["domain_id"], f"https://example.jp{path}", f"https://example.jp{path}", discovered_by="seed",
    )
    page_id = PageRepository(db).upsert(
        crawl_url_id, run_id, domain["domain_id"], f"https://example.jp{path}", f"https://example.jp{path}",
        fetched_at="2026-01-01T00:00:00",
    )
    return page_id, run_id


# ---- KeywordMetricsRepository ----

def test_keyword_metrics_record_and_idempotency(db):
    repo = KeywordMetricsRepository(db)
    metric_id = repo.record(query="q", source="manual", observed_at="2026-01-01", search_volume=500)
    assert metric_id is not None
    dup = repo.record(query="q", source="manual", observed_at="2026-01-01", search_volume=999)
    assert dup is None
    assert repo.latest_for_query("q")["search_volume"] == 500


def test_keyword_metrics_different_source_is_not_duplicate(db):
    repo = KeywordMetricsRepository(db)
    a = repo.record(query="q", source="manual", observed_at="2026-01-01", search_volume=500)
    b = repo.record(query="q", source="other_tool", observed_at="2026-01-01", search_volume=600)
    assert a is not None and b is not None
    assert len(repo.list_for_query("q")) == 2


# ---- OpportunityRepository ----

def test_opportunity_analyses_upsert_insert_then_update(db):
    page_id, run_id = _seed_page(db)
    repo = OpportunityRepository(db)
    opp_id = repo.upsert_analysis("page", page_id, page_id, crawl_run_id=run_id, overall_opportunity_score=50.0,
                                   score_status="PARTIAL", confidence_label="MEDIUM", confidence_value=0.5)
    row = repo.get_by_id(opp_id)
    assert row["overall_opportunity_score"] == 50.0

    opp_id2 = repo.upsert_analysis("page", page_id, page_id, crawl_run_id=run_id, overall_opportunity_score=80.0,
                                    score_status="COMPLETE", confidence_label="HIGH", confidence_value=0.9)
    assert opp_id2 == opp_id
    assert repo.get_by_id(opp_id)["overall_opportunity_score"] == 80.0


def test_opportunity_analyses_list_sorted_by_overall_score_desc(db):
    page_id, run_id = _seed_page(db)
    repo = OpportunityRepository(db)
    repo.upsert_analysis("page", page_id, page_id, crawl_run_id=run_id, overall_opportunity_score=30.0,
                          score_status="PARTIAL", confidence_label="MEDIUM", confidence_value=0.5)
    repo.upsert_analysis("keyword", "kw1", page_id, crawl_run_id=run_id, overall_opportunity_score=90.0,
                          score_status="COMPLETE", confidence_label="HIGH", confidence_value=0.9)
    rows = repo.list_analyses()
    assert rows[0]["overall_opportunity_score"] == 90.0


def test_opportunity_analyses_list_filters_by_min_thresholds(db):
    page_id, run_id = _seed_page(db)
    repo = OpportunityRepository(db)
    repo.upsert_analysis("page", page_id, page_id, crawl_run_id=run_id, overall_opportunity_score=30.0,
                          ai_opportunity_score=20.0, score_status="PARTIAL", confidence_label="MEDIUM",
                          confidence_value=0.5)
    rows = repo.list_analyses(min_ai_gap=50.0)
    assert rows == []
    rows2 = repo.list_analyses(min_ai_gap=10.0)
    assert len(rows2) == 1


def test_opportunity_components_replace_not_duplicate(db):
    page_id, run_id = _seed_page(db)
    repo = OpportunityRepository(db)
    opp_id = repo.upsert_analysis("page", page_id, page_id, crawl_run_id=run_id, score_status="PARTIAL",
                                   confidence_label="MEDIUM", confidence_value=0.5)
    repo.replace_components(opp_id, [
        {"component_name": "demand_score", "value": 10.0, "weight": 10.0, "availability": "OBSERVED", "evidence": "e1"},
    ])
    repo.replace_components(opp_id, [
        {"component_name": "demand_score", "value": 20.0, "weight": 10.0, "availability": "OBSERVED", "evidence": "e2"},
    ])
    components = repo.components_for(opp_id)
    assert len(components) == 1
    assert components[0]["value"] == 20.0


def test_opportunity_reasons_and_actions_replace_not_duplicate(db):
    page_id, run_id = _seed_page(db)
    repo = OpportunityRepository(db)
    opp_id = repo.upsert_analysis("page", page_id, page_id, crawl_run_id=run_id, score_status="PARTIAL",
                                   confidence_label="MEDIUM", confidence_value=0.5)
    for _ in range(2):
        repo.replace_reasons(opp_id, [
            {"reason_code": "CONTENT_GAP", "reason_text": "t", "impact_score": 50.0, "evidence_reference": "e"},
        ])
        repo.replace_actions(opp_id, [
            {"action_code": "ADD_NUMERIC_FACTS", "priority": "HIGH", "reason_code": "CONTENT_GAP",
             "target_page": page_id, "target_keyword": None},
        ])
    assert len(repo.reasons_for(opp_id)) == 1
    assert len(repo.actions_for(opp_id)) == 1


# ---- ComparisonRepository ----

def test_comparison_repository_upsert_insert_then_update(db):
    repo = ComparisonRepository(db)
    cid = repo.upsert("page", "p1", "page", "p2", "organic_rank", 3.0, 10.0, -7.0, "left", "HIGH", "e1")
    cid2 = repo.upsert("page", "p1", "page", "p2", "organic_rank", 5.0, 10.0, -5.0, "left", "MEDIUM", "e2")
    assert cid == cid2
    row = repo.list_for_pair("page", "p1", "page", "p2")[0]
    assert row["left_value"] == 5.0


def test_comparison_repository_list_for_entity_matches_either_side(db):
    repo = ComparisonRepository(db)
    repo.upsert("page", "p1", "page", "p2", "organic_rank", 3.0, 10.0, -7.0, "left", "HIGH", None)
    repo.upsert("page", "p3", "page", "p1", "readiness", 80.0, 20.0, 60.0, "left", "MEDIUM", None)
    results = repo.list_for_entity("page", "p1")
    assert len(results) == 2


# ---- ContentGapRepository ----

def test_content_gap_repository_upsert_insert_then_update(db):
    from db_collector_os.competitive_intelligence.opportunity.content_gap import ContentGapResult

    page_id, run_id = _seed_page(db)
    competitor_id, _ = _seed_page(db)
    repo = ContentGapRepository(db)
    result1 = ContentGapResult(["a"], [], [], [], [], [], [], [], [], 10.0)
    repo.upsert(page_id, competitor_id, result1)
    result2 = ContentGapResult(["a", "b"], [], [], [], [], [], [], [], [], 20.0)
    repo.upsert(page_id, competitor_id, result2)
    row = repo.get(page_id, competitor_id)
    assert row["content_gap_score"] == 20.0
    import json
    assert json.loads(row["missing_keywords_json"]) == ["a", "b"]


def test_content_gap_repository_list_for_our_page_sorted_by_score(db):
    from db_collector_os.competitive_intelligence.opportunity.content_gap import ContentGapResult

    page_id, run_id = _seed_page(db)
    c1, _ = _seed_page(db)
    c2, _ = _seed_page(db)
    repo = ContentGapRepository(db)
    repo.upsert(page_id, c1, ContentGapResult([], [], [], [], [], [], [], [], [], 10.0))
    repo.upsert(page_id, c2, ContentGapResult([], [], [], [], [], [], [], [], [], 90.0))
    rows = repo.list_for_our_page(page_id)
    assert rows[0]["content_gap_score"] == 90.0
