"""Full-pipeline integration tests for the FIRST_PRODUCTION_DB job shape
(collector_type=official_site, adapter=figure_official_site), against a
small mocked site built from the figure fixtures. No real network access.

Covers, beyond the adapter-unit tests in test_figure_adapter.py: entity
normalization/canonical URL/dedup end to end, evidence provenance,
checkpoint persistence, retry/backoff + one-URL-failure isolation, per-domain
rate limiting, max_pages capping, and incremental revalidation (ETag/304).
"""

from __future__ import annotations

from pathlib import Path

import responses

from db_collector_os.collectors import CollectorContext, get_collector
from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType, JobPhase
from db_collector_os.worker import Worker

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def make_figure_job(jr: JobRegistry, **overrides) -> str:
    defaults = dict(
        job_name="Figure Official Site (test)", category="figure", target_db="figure_official_site_test",
        target_table="entities", collector_type=CollectorType.OFFICIAL_SITE, adapter="figure_official_site",
        priority=50, schedule="@daily", max_pages=10, max_depth=3, concurrency=1, rate_limit=0.0,
        config={
            "seed_urls": ["https://figures.example.com/products"],
            "discovery": {
                "robots_seed_urls": ["https://figures.example.com/"],
                "internal_links": True,
                "related_entities": True,
                "allowed_domains": ["figures.example.com"],
            },
            "phase1_conditions": {"queue_empty": True, "require_discovery_saturation": True, "min_entity_count": 1},
        },
    )
    defaults.update(overrides)
    return jr.create(**defaults)


def _mock_base_site():
    responses.add(responses.GET, "https://figures.example.com/robots.txt", status=404)
    responses.add(
        responses.GET, "https://figures.example.com/products", status=200, content_type="text/html",
        body=load_fixture("figure_list.html"),
    )
    responses.add(
        responses.GET, "https://figures.example.com/products/hana-1-7", status=200, content_type="text/html",
        body=load_fixture("figure_detail_full.html"),
    )
    responses.add(
        responses.GET, "https://figures.example.com/products/yuki-1-8", status=200, content_type="text/html",
        body=load_fixture("figure_detail_noisy.html"),
    )


@responses.activate
def test_pipeline_creates_entities_with_evidence_and_skips_list_page(app_config, db):
    _mock_base_site()
    jr = JobRegistry(db)
    job_id = make_figure_job(jr)
    worker = Worker(app_config, worker_id="figure-test-worker", db=db)

    for _ in range(4):
        jr.mark_queued(job_id)
        worker.run_one_job()

    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    names = {e["name"] for e in entities}
    assert "花 1/7スケールフィギュア" in names
    assert "雪 1/8スケールフィギュア" in names
    # the list page itself must never become an entity
    assert "フィギュア一覧" not in names

    hana = next(e for e in entities if e["name"] == "花 1/7スケールフィギュア")
    assert hana["external_id"] == "4900000012345"
    assert hana["entity_type"] == "figure"

    evidence = db.query("SELECT * FROM evidence WHERE entity_id=?", (hana["entity_id"],))
    assert len(evidence) > 0
    assert all(e["source_url"] == "https://figures.example.com/products/hana-1-7" for e in evidence)
    assert all(e["fetched_at"] for e in evidence)

    # the list page's fetch-queue row is 'done', but produced no review item
    review_rows = db.query("SELECT * FROM review_queue WHERE job_id=?", (job_id,))
    assert not any("フィギュア一覧" in (r["details"] or "") for r in review_rows)


@responses.activate
def test_missing_required_field_page_goes_to_review(app_config, db):
    _mock_base_site()
    responses.add(
        responses.GET, "https://figures.example.com/products/broken-listing", status=200, content_type="text/html",
        body=load_fixture("figure_detail_missing_name.html"),
    )
    jr = JobRegistry(db)
    job_id = make_figure_job(jr, config={
        "seed_urls": [
            "https://figures.example.com/products",
            "https://figures.example.com/products/broken-listing",
        ],
        "discovery": {"internal_links": True, "related_entities": True, "allowed_domains": ["figures.example.com"]},
    })
    worker = Worker(app_config, worker_id="figure-test-worker-2", db=db)
    for _ in range(3):
        jr.mark_queued(job_id)
        worker.run_one_job()

    review_rows = db.query(
        "SELECT * FROM review_queue WHERE job_id=? AND reason='missing_required_field'", (job_id,)
    )
    assert len(review_rows) == 1
    assert "name" in review_rows[0]["details"]


@responses.activate
def test_duplicate_across_urls_merges_via_gtin(app_config, db):
    responses.add(responses.GET, "https://figures.example.com/robots.txt", status=404)
    responses.add(
        responses.GET, "https://figures.example.com/products/hana-1-7", status=200, content_type="text/html",
        body=load_fixture("figure_detail_full.html"),
    )
    responses.add(
        responses.GET, "https://figures.example.com/products/hana-1-7-rerelease", status=200, content_type="text/html",
        body=load_fixture("figure_detail_duplicate.html"),
    )
    jr = JobRegistry(db)
    job_id = make_figure_job(jr, config={
        "seed_urls": [
            "https://figures.example.com/products/hana-1-7",
            "https://figures.example.com/products/hana-1-7-rerelease",
        ],
        "discovery": {"internal_links": False, "related_entities": False},
    })
    worker = Worker(app_config, worker_id="figure-test-worker-3", db=db)
    for _ in range(3):
        jr.mark_queued(job_id)
        worker.run_one_job()

    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert len(entities) == 1  # merged, not duplicated
    assert entities[0]["external_id"] == "4900000012345"

    run_rows = db.query("SELECT * FROM run_history WHERE job_id=?", (job_id,))
    assert sum(r["duplicate_count"] for r in run_rows) >= 1


@responses.activate
def test_checkpoint_persists_across_simulated_restart(app_config, db):
    _mock_base_site()
    jr = JobRegistry(db)
    job_id = make_figure_job(jr)
    worker = Worker(app_config, worker_id="figure-test-worker-4", db=db)

    jr.mark_queued(job_id)
    worker.run_one_job()

    checkpoint = worker.ctx.checkpoints.load(job_id)
    assert checkpoint["state"].get("seeded") is True

    # A "process restart": build a brand new Worker (fresh CollectorContext)
    # against the same db handle and confirm checkpoint state is visible.
    worker2 = Worker(app_config, worker_id="figure-test-worker-4b", db=db)
    checkpoint2 = worker2.ctx.checkpoints.load(job_id)
    assert checkpoint2["state"].get("seeded") is True
    assert checkpoint2["phase"] in (
        JobPhase.DISCOVERY, JobPhase.COLLECT, JobPhase.VALIDATION, JobPhase.PHASE1_COMPLETE,
    )


@responses.activate
def test_domain_rate_limit_defers_second_fetch_same_domain(app_config, db):
    _mock_base_site()
    jr = JobRegistry(db)
    # a real per-domain delay this time, unlike the 0.0 default used elsewhere
    job_id = make_figure_job(jr, rate_limit=30.0, config={
        "seed_urls": [
            "https://figures.example.com/products/hana-1-7",
            "https://figures.example.com/products/yuki-1-8",
        ],
        "discovery": {"internal_links": False, "related_entities": False},
    })
    ctx = CollectorContext.build(app_config, db)
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    job = jr.get(job_id)
    collector = get_collector(job["collector_type"], ctx)
    outcome = collector.run_once(job)

    # Both URLs share a domain and rate_limit=30s -> only the first is fetched
    # in this run; the second stays queued for a later, rate-limit-respecting run.
    assert outcome.fetched == 1
    assert ctx.fetch_queue.pending_count(job_id) == 1


@responses.activate
def test_max_pages_caps_fetches_per_run(app_config, db):
    _mock_base_site()
    jr = JobRegistry(db)
    job_id = make_figure_job(jr, max_pages=1, config={
        "seed_urls": [
            "https://figures.example.com/products/hana-1-7",
            "https://figures.example.com/products/yuki-1-8",
        ],
        "discovery": {"internal_links": False, "related_entities": False},
    })
    ctx = CollectorContext.build(app_config, db)
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    job = jr.get(job_id)
    collector = get_collector(job["collector_type"], ctx)
    outcome = collector.run_once(job)

    assert outcome.fetched == 1  # max_pages=1 honored even though 2 URLs were queued
    assert ctx.fetch_queue.pending_count(job_id) == 1


@responses.activate
def test_retry_then_permanent_failure_does_not_block_other_entities(app_config, db):
    responses.add(responses.GET, "https://figures.example.com/robots.txt", status=404)
    responses.add(
        responses.GET, "https://figures.example.com/products/hana-1-7", status=200, content_type="text/html",
        body=load_fixture("figure_detail_full.html"),
    )
    # Always 503: this URL should retry with backoff, eventually fail
    # permanently, and never prevent the other (good) URL from succeeding.
    responses.add(responses.GET, "https://figures.example.com/products/down", status=503)
    responses.add(responses.GET, "https://figures.example.com/products/down", status=503)

    jr = JobRegistry(db)
    job_id = make_figure_job(jr, config={
        "seed_urls": [
            "https://figures.example.com/products/hana-1-7",
            "https://figures.example.com/products/down",
        ],
        "discovery": {"internal_links": False, "related_entities": False},
    })
    ctx = CollectorContext.build(app_config, db)

    # force a tiny max_attempts on the bad URL so the test doesn't need many cycles
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    job = jr.get(job_id)
    collector = get_collector(job["collector_type"], ctx)
    collector.run_once(job)
    db.execute("UPDATE fetch_queue SET max_attempts=2 WHERE job_id=? AND url LIKE '%down%'", (job_id,))

    for _ in range(3):
        # Backoff schedules the next attempt in the future (exponential); jump
        # straight past that wait instead of sleeping in a test.
        db.execute(
            "UPDATE fetch_queue SET next_retry_at=NULL WHERE job_id=? AND url LIKE '%down%' AND status='queued'",
            (job_id,),
        )
        jr.finish(job_id, "completed")
        jr.mark_queued(job_id)
        jr.claim_queued(job_id)
        job = jr.get(job_id)
        collector.run_once(job)

    bad_row = db.query_one("SELECT * FROM fetch_queue WHERE job_id=? AND url LIKE '%down%'", (job_id,))
    assert bad_row["status"] == "failed"
    assert bad_row["attempt_count"] >= 2

    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert any(e["name"] == "花 1/7スケールフィギュア" for e in entities)

    review_rows = db.query("SELECT * FROM review_queue WHERE job_id=? AND reason='parse_failure'", (job_id,))
    assert len(review_rows) >= 1


@responses.activate
def test_incremental_revalidation_uses_conditional_get(app_config, db):
    _mock_base_site()
    jr = JobRegistry(db)
    job_id = make_figure_job(jr, config={
        "seed_urls": ["https://figures.example.com/products/hana-1-7"],
        "discovery": {"internal_links": False, "related_entities": False},
        # revalidate immediately regardless of how recently it was fetched,
        # so the test doesn't need to wait out the (production) default delay
        "incremental_revalidate_after_seconds": 0,
    })
    ctx = CollectorContext.build(app_config, db)
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    job = jr.get(job_id)
    collector = get_collector(job["collector_type"], ctx)
    collector.run_once(job)

    entities_before = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert len(entities_before) == 1

    # Fast-forward straight to incremental and simulate the site saying
    # "unchanged" via a conditional GET.
    db.execute("UPDATE jobs SET phase=? WHERE job_id=?", (JobPhase.INCREMENTAL, job_id))
    responses.replace(
        responses.GET, "https://figures.example.com/products/hana-1-7", status=304,
    )

    jr.finish(job_id, "completed")
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    job = jr.get(job_id)
    collector.run_once(job)

    entities_after = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert len(entities_after) == 1  # a 304 must not create a duplicate entity
    assert entities_after[0]["entity_id"] == entities_before[0]["entity_id"]

    done_row = db.query_one(
        "SELECT * FROM fetch_queue WHERE job_id=? AND url LIKE '%hana%'", (job_id,)
    )
    assert done_row["last_http_status"] == 304
