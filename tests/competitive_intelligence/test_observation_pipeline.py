from __future__ import annotations

import responses

from db_collector_os.competitive_intelligence.ai_search import analyze_ai_page
from db_collector_os.competitive_intelligence.ai_search.observation.pipeline import (
    get_page_visibility,
    recompute_page_visibility,
)
from db_collector_os.competitive_intelligence.ai_search.observation.repository import (
    AioObservationRepository,
    AiModeObservationRepository,
    FanoutObservationRepository,
    SerpObservationRepository,
)
from db_collector_os.competitive_intelligence.ai_search.repository import AiFanoutQueryRepository
from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.repository.pages import PageRepository

_HTML = """<!doctype html><html><head><title>渋谷ラーメンおすすめランキング【独自調査】</title>
<link rel="canonical" href="https://example.jp/ramen/"></head><body>
<main><h1>渋谷のラーメンおすすめランキング【独自調査】</h1>
<p>編集部が実際に42店舗を食べ比べ、独自調査した結果をもとにランキングを作成しました。</p></main>
</body></html>"""


def _crawl(db, url: str = "https://example.jp/ramen/"):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, url, body=_HTML, content_type="text/html")
        engine = CrawlEngine(db, user_agent="TestBot/1.0")
        run_id = engine.start_advertiser_lp(url, requested_mode="advertiser_lp")
    return PageRepository(db).list_for_run(run_id, limit=1)[0]


def _set_readiness_score(db, page_id: str, score: int) -> None:
    db.execute("UPDATE ci_ai_page_analysis SET ai_citation_readiness_score=? WHERE page_id=?", (score, page_id))


def test_get_page_visibility_none_before_recompute(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    assert get_page_visibility(db, page["page_id"]) is None


def test_recompute_unknown_page_raises(db):
    import pytest
    with pytest.raises(ValueError):
        recompute_page_visibility(db, "no-such-page")


def test_recompute_with_zero_observations_is_all_null_not_zero(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    result = recompute_page_visibility(db, page["page_id"])
    for field in (
        "organic_rank", "organic_top3", "aio_cited", "aio_citation_position", "aio_citation_frequency",
        "ai_mode_cited", "ai_mode_citation_frequency", "fanout_visibility_rate", "readiness_vs_reality_class",
        "organic_aio_cross_class",
    ):
        assert result[field] is None, f"{field} must be NULL with zero observations, got {result[field]!r}"
    assert result["aio_observation_count"] == 0
    assert result["ai_mode_observation_count"] == 0
    assert result["fanout_queries_total"] > 0  # PHASE 12 already generated fan-out candidates
    assert result["fanout_queries_observed"] == 0


def test_recompute_computes_organic_rank_and_bands(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    query = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]["base_keyword"]
    SerpObservationRepository(db).record(
        query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available",
        results=[{"result_position": 7, "result_url": page["url"], "normalized_url": page["normalized_url"],
                  "result_domain": "example.jp"}],
    )
    result = recompute_page_visibility(db, page["page_id"])
    assert result["organic_rank"] == 7
    assert result["organic_top3"] == 0
    assert result["organic_top10"] == 1
    assert result["organic_top20"] == 1


def test_recompute_picks_latest_organic_observation_by_time(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    query = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]["base_keyword"]
    repo = SerpObservationRepository(db)
    repo.record(query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
                provider="manual", status="available",
                results=[{"result_position": 20, "result_url": page["url"], "normalized_url": page["normalized_url"],
                          "result_domain": "example.jp"}])
    repo.record(query=query, country="JP", language="ja", device="desktop", observed_at="2026-02-01T00:00:00Z",
                provider="manual", status="available",
                results=[{"result_position": 2, "result_url": page["url"], "normalized_url": page["normalized_url"],
                          "result_domain": "example.jp"}])
    result = recompute_page_visibility(db, page["page_id"])
    assert result["organic_rank"] == 2


def test_recompute_aio_citation_frequency_and_persistence(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    query = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]["base_keyword"]
    aio_repo = AioObservationRepository(db)
    # cited once, not cited once -> frequency 0.5
    aio_repo.record(query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
                     provider="manual", status="available", aio_present=True,
                     citations=[{"citation_position": 1, "citation_url": page["url"],
                                 "normalized_url": page["normalized_url"], "citation_domain": "example.jp"}])
    aio_repo.record(query=query, country="JP", language="ja", device="desktop", observed_at="2026-02-01T00:00:00Z",
                     provider="manual", status="available", aio_present=True, citations=[])
    result = recompute_page_visibility(db, page["page_id"])
    assert result["aio_cited"] == 1
    assert result["aio_observation_count"] == 2
    assert result["aio_citation_count"] == 1
    assert result["aio_citation_frequency"] == 0.5
    assert result["aio_first_seen"] == "2026-01-01T00:00:00Z"
    assert result["aio_last_seen"] == "2026-01-01T00:00:00Z"


def test_recompute_never_cited_is_false_not_null_once_observed(db):
    """Observed-but-never-cited must be distinguishable from
    never-observed: False, not None."""
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    query = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]["base_keyword"]
    AioObservationRepository(db).record(
        query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available", aio_present=True, citations=[],
    )
    result = recompute_page_visibility(db, page["page_id"])
    assert result["aio_cited"] == 0
    assert result["aio_observation_count"] == 1
    assert result["aio_citation_count"] == 0


def test_recompute_aio_and_ai_mode_are_independent(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    query = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]["base_keyword"]
    AioObservationRepository(db).record(
        query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available", aio_present=True,
        citations=[{"citation_position": 1, "citation_url": page["url"],
                    "normalized_url": page["normalized_url"], "citation_domain": "example.jp"}],
    )
    result = recompute_page_visibility(db, page["page_id"])
    assert result["aio_cited"] == 1
    assert result["ai_mode_cited"] is None  # AI Mode never observed at all


def test_recompute_fanout_visibility_rollup(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    fanout_queries = AiFanoutQueryRepository(db).list_for_page(page["page_id"])
    fq = fanout_queries[0]
    FanoutObservationRepository(db).record(
        fanout_query_id=fq["fanout_query_id"], parent_query=fq["base_keyword"], fanout_query=fq["subquery_text"],
        fanout_intent=fq["intent_class"], country="JP", language="ja", device="desktop",
        observed_at="2026-01-01T00:00:00Z", provider="manual", status="available",
        target_page_id=page["page_id"], target_rank=8, target_cited=False, result_urls=[page["url"]],
    )
    result = recompute_page_visibility(db, page["page_id"])
    assert result["fanout_queries_observed"] == 1
    assert result["fanout_top10_count"] == 1
    assert result["fanout_visibility_rate"] == 1.0  # rank found -> visible, even though not cited


def test_recompute_fanout_not_found_is_not_visible(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    fq = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]
    FanoutObservationRepository(db).record(
        fanout_query_id=fq["fanout_query_id"], parent_query=fq["base_keyword"], fanout_query=fq["subquery_text"],
        fanout_intent=fq["intent_class"], country="JP", language="ja", device="desktop",
        observed_at="2026-01-01T00:00:00Z", provider="manual", status="available",
        target_page_id=page["page_id"], target_rank=None, target_cited=False, result_urls=[],
    )
    result = recompute_page_visibility(db, page["page_id"])
    assert result["fanout_visibility_rate"] == 0.0


# ---- Readiness-vs-Reality: the four A/B/C/D scenarios ----

def test_readiness_vs_reality_high_readiness_not_cited_is_b(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    _set_readiness_score(db, page["page_id"], 80)
    query = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]["base_keyword"]
    AioObservationRepository(db).record(
        query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available", aio_present=True, citations=[],
    )
    AiModeObservationRepository(db).record(
        query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available", citations=[],
    )
    result = recompute_page_visibility(db, page["page_id"])
    assert result["readiness_vs_reality_class"] == "B"
    assert result["signal_high_readiness_not_cited"] == 1


def test_readiness_vs_reality_low_readiness_cited_is_c(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    _set_readiness_score(db, page["page_id"], 10)
    query = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]["base_keyword"]
    AioObservationRepository(db).record(
        query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available", aio_present=True,
        citations=[{"citation_position": 1, "citation_url": page["url"],
                    "normalized_url": page["normalized_url"], "citation_domain": "example.jp"}],
    )
    result = recompute_page_visibility(db, page["page_id"])
    assert result["readiness_vs_reality_class"] == "C"


def test_readiness_vs_reality_high_readiness_cited_is_a(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    _set_readiness_score(db, page["page_id"], 90)
    query = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]["base_keyword"]
    AioObservationRepository(db).record(
        query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available", aio_present=True,
        citations=[{"citation_position": 1, "citation_url": page["url"],
                    "normalized_url": page["normalized_url"], "citation_domain": "example.jp"}],
    )
    result = recompute_page_visibility(db, page["page_id"])
    assert result["readiness_vs_reality_class"] == "A"


def test_readiness_vs_reality_low_readiness_not_cited_is_d(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    _set_readiness_score(db, page["page_id"], 10)
    query = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]["base_keyword"]
    AioObservationRepository(db).record(
        query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available", aio_present=True, citations=[],
    )
    AiModeObservationRepository(db).record(
        query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available", citations=[],
    )
    result = recompute_page_visibility(db, page["page_id"])
    assert result["readiness_vs_reality_class"] == "D"


def test_readiness_vs_reality_stays_none_without_ai_mode_data_even_if_aio_present_is_false(db):
    """cited must come from *known* AIO+AI-Mode status, not from AIO alone
    when AI Mode was never checked."""
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    _set_readiness_score(db, page["page_id"], 80)
    query = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]["base_keyword"]
    AioObservationRepository(db).record(
        query=query, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available", aio_present=True, citations=[],
    )
    result = recompute_page_visibility(db, page["page_id"])
    assert result["readiness_vs_reality_class"] is None


def test_recompute_is_idempotent_and_upserts_not_duplicates(db):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    first = recompute_page_visibility(db, page["page_id"])
    second = recompute_page_visibility(db, page["page_id"])
    assert first["page_id"] == second["page_id"]
    rows = db.query("SELECT COUNT(*) AS n FROM ci_ai_page_visibility WHERE page_id=?", (page["page_id"],))
    assert rows[0]["n"] == 1
