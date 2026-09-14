from __future__ import annotations

from db_collector_os.competitive_intelligence.ai_search.observation.repository import (
    AioObservationRepository,
    AiModeObservationRepository,
    FanoutObservationRepository,
    GscObservationRepository,
    ImportBatchRepository,
    PageVisibilityRepository,
    SerpObservationRepository,
)
from db_collector_os.competitive_intelligence.repository.core import (
    CrawlRunRepository,
    CrawlUrlRepository,
    DomainRepository,
)
from db_collector_os.competitive_intelligence.repository.pages import PageRepository


def _seed_page(db) -> tuple[str, str]:
    """Minimal FK-satisfying page + crawl_run, without a real crawl --
    good enough for repository-level tests that only need valid ids."""
    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(
        domain["domain_id"], "https://example.jp/", "affiliate_domain", "affiliate_domain", "general",
    )
    crawl_url_id, _ = CrawlUrlRepository(db).add(
        run_id, domain["domain_id"], "https://example.jp/a", "https://example.jp/a", discovered_by="seed",
    )
    page_id = PageRepository(db).upsert(
        crawl_url_id, run_id, domain["domain_id"], "https://example.jp/a", "https://example.jp/a",
        fetched_at="2026-01-01T00:00:00",
    )
    return page_id, run_id


# ---- SerpObservationRepository ----

def test_serp_observation_record_and_idempotency(db):
    repo = SerpObservationRepository(db)
    obs_id = repo.record(
        query="q", country="JP", language="ja", device="desktop", observed_at="2026-01-01", provider="manual",
        status="available",
        results=[{"result_position": 1, "result_url": "https://x.example/", "normalized_url": "https://x.example",
                  "result_domain": "x.example"}],
    )
    assert obs_id is not None
    dup = repo.record(
        query="q", country="JP", language="ja", device="desktop", observed_at="2026-01-01", provider="manual",
        status="available", results=[],
    )
    assert dup is None

    results = repo.results_for_observation(obs_id)
    assert len(results) == 1
    assert repo.find_result_by_url(obs_id, "https://x.example") is not None
    assert repo.latest_for_query("q", "JP", "ja", "desktop")["serp_observation_id"] == obs_id


# ---- AioObservationRepository / AiModeObservationRepository ----

def test_aio_observation_record_with_citations(db):
    repo = AioObservationRepository(db)
    obs_id = repo.record(
        query="q", country="JP", language="ja", device="desktop", observed_at="2026-01-01", provider="manual",
        status="available", aio_present=True,
        citations=[{"citation_position": 1, "citation_url": "https://x.example/",
                    "normalized_url": "https://x.example", "citation_domain": "x.example"}],
    )
    citations = repo.citations_for_observation(obs_id)
    assert len(citations) == 1
    by_url = repo.citations_for_url("https://x.example")
    assert len(by_url) == 1
    assert by_url[0]["query"] == "q"


def test_ai_mode_observations_stored_separately_from_aio(db):
    aio_repo = AioObservationRepository(db)
    ai_mode_repo = AiModeObservationRepository(db)
    aio_repo.record(query="q", country="JP", language="ja", device="desktop", observed_at="2026-01-01",
                     provider="manual", status="available", citations=[])
    # Same query/observed_at/provider is a completely separate table -- no collision.
    obs_id = ai_mode_repo.record(query="q", country="JP", language="ja", device="desktop", observed_at="2026-01-01",
                                  provider="manual", status="available", citations=[])
    assert obs_id is not None
    assert ai_mode_repo.list_for_query("q", "JP", "ja", "desktop")
    assert aio_repo.list_for_query("q", "JP", "ja", "desktop")


def test_aio_and_ai_mode_idempotency(db):
    ai_mode_repo = AiModeObservationRepository(db)
    first = ai_mode_repo.record(query="q", country="JP", language="ja", device="desktop", observed_at="2026-01-01",
                                 provider="manual", status="available", citations=[])
    dup = ai_mode_repo.record(query="q", country="JP", language="ja", device="desktop", observed_at="2026-01-01",
                               provider="manual", status="available", citations=[])
    assert first is not None
    assert dup is None


# ---- FanoutObservationRepository ----

def test_fanout_observation_record_and_list(db):
    from db_collector_os.competitive_intelligence.ai_search.repository import AiFanoutQueryRepository

    page_id, _run_id = _seed_page(db)
    AiFanoutQueryRepository(db).replace_for_page(page_id, [
        {"base_keyword": "kw", "subquery_text": "kwとは", "intent_class": "informational", "covered_by_content": False},
    ])
    fanout_query_id = AiFanoutQueryRepository(db).list_for_page(page_id)[0]["fanout_query_id"]

    repo = FanoutObservationRepository(db)
    obs_id = repo.record(
        fanout_query_id=fanout_query_id, parent_query="kw", fanout_query="kwとは", fanout_intent="informational",
        country="JP", language="ja", device="desktop", observed_at="2026-01-01", provider="manual",
        status="available", target_page_id=page_id, target_rank=5, target_cited=True,
        result_urls=["https://example.jp/a"],
    )
    assert obs_id is not None
    for_page = repo.list_for_page(page_id)
    assert len(for_page) == 1
    assert for_page[0]["target_rank"] == 5
    assert repo.list_for_fanout_query(fanout_query_id) == for_page


# ---- PageVisibilityRepository ----

def test_page_visibility_upsert_insert_then_update(db):
    page_id, run_id = _seed_page(db)
    repo = PageVisibilityRepository(db)
    assert repo.get(page_id) is None

    repo.upsert(page_id, run_id, organic_rank=5, aio_cited=None)
    row = repo.get(page_id)
    assert row["organic_rank"] == 5
    assert row["aio_cited"] is None

    repo.upsert(page_id, run_id, organic_rank=3, aio_cited=1)
    row2 = repo.get(page_id)
    assert row2["organic_rank"] == 3
    assert row2["aio_cited"] == 1


def test_page_visibility_upsert_rejects_unknown_field(db):
    import pytest

    page_id, run_id = _seed_page(db)
    with pytest.raises(ValueError):
        PageVisibilityRepository(db).upsert(page_id, run_id, not_a_real_column=1)


def test_page_visibility_list_for_run(db):
    page_id, run_id = _seed_page(db)
    PageVisibilityRepository(db).upsert(page_id, run_id, organic_rank=1)
    rows = PageVisibilityRepository(db).list_for_run(run_id)
    assert len(rows) == 1
    assert rows[0]["page_id"] == page_id


# ---- ImportBatchRepository ----

def test_import_batch_idempotent_on_file_hash_and_type(db):
    repo = ImportBatchRepository(db)
    batch_id = repo.record(
        file_path="/tmp/f.json", file_hash="hash1", observation_type="organic", provider="manual",
        imported_count=1, skipped_duplicate_count=0, error_count=0,
    )
    assert batch_id is not None
    dup = repo.record(
        file_path="/tmp/f.json", file_hash="hash1", observation_type="organic", provider="manual",
        imported_count=1, skipped_duplicate_count=0, error_count=0,
    )
    assert dup is None
    assert repo.get(batch_id)["file_hash"] == "hash1"
    assert len(repo.list_recent()) == 1


def test_import_batch_same_hash_different_type_is_not_a_duplicate(db):
    repo = ImportBatchRepository(db)
    a = repo.record(file_path="/tmp/f.json", file_hash="hash1", observation_type="organic", provider=None,
                     imported_count=1, skipped_duplicate_count=0, error_count=0)
    b = repo.record(file_path="/tmp/f.json", file_hash="hash1", observation_type="aio", provider=None,
                     imported_count=1, skipped_duplicate_count=0, error_count=0)
    assert a is not None and b is not None and a != b


# ---- GscObservationRepository ----

def test_gsc_observation_record_and_idempotency_with_nullable_country_device(db):
    repo = GscObservationRepository(db)
    obs_id = repo.record(
        gsc_query="q", gsc_page="https://example.jp/a", normalized_page="https://example.jp/a",
        observed_date="2026-01-01", country=None, device=None,
    )
    assert obs_id is not None
    dup = repo.record(
        gsc_query="q", gsc_page="https://example.jp/a", normalized_page="https://example.jp/a",
        observed_date="2026-01-01", country=None, device=None,
    )
    assert dup is None
    assert len(repo.list_for_page("https://example.jp/a")) == 1
