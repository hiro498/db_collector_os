"""Full-pipeline integration tests for the 全国ラブホテル施設DB job shape
(collector_type=local_business, adapter=lovehotel_couples), against a
small mocked couples.jp-shaped site. No real network access (uses
`responses` to mock HTTP, mirroring test_figure_pipeline_integration.py).

Covers, beyond the adapter/discovery unit tests: end-to-end entity
creation + evidence with an area-listing page correctly skipped, a
missing-name page routed to review, exact-duplicate-URL suppression,
cross-URL dedup via facility ID (merge), ambiguous same-name/different-
address duplicates routed to review (never silently merged), HTTP error
isolation, and checkpoint persistence across a simulated restart.
"""

from __future__ import annotations

import responses

from db_collector_os.collectors import CollectorContext, get_collector
from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType
from db_collector_os.worker import Worker


def _facility_html(url: str, name: str, postal: str, address_rest: str, tel: str, official_href: str | None = None) -> str:
    official_block = (
        f'<div class="official-link"><a href="{official_href}">公式サイトはこちら</a></div>'
        if official_href else ""
    )
    return f"""
    <html><head><meta charset="utf-8"><title>{name}</title>
    <link rel="canonical" href="{url}"></head>
    <body>
      <h1>{name}</h1>
      <p>〒{postal} {address_rest}</p>
      <p>Tel: {tel}</p>
      {official_block}
    </body></html>
    """


def _list_html(url: str, title: str, hotel_urls: list[str]) -> str:
    links = "\n".join(f'<li><a href="{u}">Hotel</a></li>' for u in hotel_urls)
    return f"""
    <html><head><meta charset="utf-8"><title>{title}</title>
    <link rel="canonical" href="{url}"></head>
    <body><h1>{title}</h1><ul>{links}</ul></body></html>
    """


def make_lovehotel_job(jr: JobRegistry, **overrides) -> str:
    defaults = dict(
        job_name="Love Hotel Nationwide - Couples (test)", category="love_hotel",
        target_db="lovehotel_facilities_test", target_table="entities",
        collector_type=CollectorType.LOCAL_BUSINESS, adapter="lovehotel_couples",
        priority=50, schedule="@daily", max_pages=10, max_depth=3, concurrency=1, rate_limit=0.0,
        config={
            "seed_urls": ["https://couples.jp/tokyo"],
            "discovery": {
                "robots_seed_urls": ["https://couples.jp/"],
                "internal_links": True,
                "related_entities": False,
                "allowed_domains": ["couples.jp"],
            },
            "phase1_conditions": {"queue_empty": True, "require_discovery_saturation": True, "min_entity_count": 1},
        },
    )
    defaults.update(overrides)
    return jr.create(**defaults)


def _mock_base_site():
    responses.add(responses.GET, "https://couples.jp/robots.txt", status=404)
    responses.add(
        responses.GET, "https://couples.jp/tokyo", status=200, content_type="text/html",
        body=_list_html(
            "https://couples.jp/tokyo", "東京都のラブホテル一覧",
            ["https://couples.jp/hotel-details/12345", "https://couples.jp/hotel-details/23456"],
        ),
    )
    responses.add(
        responses.GET, "https://couples.jp/hotel-details/12345", status=200, content_type="text/html",
        body=_facility_html(
            "https://couples.jp/hotel-details/12345", "ホテル アルファ", "150-0001", "東京都渋谷区神宮前1-2-3",
            "03-1111-2222", official_href="https://alpha-hotel.example.com/",
        ),
    )
    responses.add(
        responses.GET, "https://couples.jp/hotel-details/23456", status=200, content_type="text/html",
        body=_facility_html(
            "https://couples.jp/hotel-details/23456", "ホテル ベータ", "160-0022", "東京都新宿区新宿1-1-1", "03-2222-3333",
        ),
    )


@responses.activate
def test_pipeline_creates_entities_with_evidence_and_skips_area_list(app_config, db):
    _mock_base_site()
    jr = JobRegistry(db)
    job_id = make_lovehotel_job(jr)
    worker = Worker(app_config, worker_id="lovehotel-test-worker", db=db)

    for _ in range(4):
        jr.mark_queued(job_id)
        worker.run_one_job()

    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    names = {e["name"] for e in entities}
    assert "ホテル アルファ" in names
    assert "ホテル ベータ" in names
    # the area-listing page itself must never become an entity:
    assert "東京都のラブホテル一覧" not in names

    alpha = next(e for e in entities if e["name"] == "ホテル アルファ")
    assert alpha["entity_type"] == "love_hotel"
    assert alpha["external_id"] == "12345"
    assert alpha["address"] and "神宮前" in alpha["address"]

    import json as _json
    alpha_data = _json.loads(alpha["data_json"])
    assert alpha_data["prefecture"] == "東京都"
    assert alpha_data["official_url"] == "https://alpha-hotel.example.com/"
    assert alpha_data["source_name"] == "Couples"

    evidence = db.query("SELECT * FROM evidence WHERE entity_id=?", (alpha["entity_id"],))
    assert len(evidence) > 0
    assert all(e["source_url"] == "https://couples.jp/hotel-details/12345" for e in evidence)

    # the list page's fetch-queue row is 'done' but produced no review noise:
    review_rows = db.query("SELECT * FROM review_queue WHERE job_id=?", (job_id,))
    assert not any("一覧" in (r["details"] or "") for r in review_rows)


@responses.activate
def test_missing_name_facility_page_goes_to_review(app_config, db):
    responses.add(responses.GET, "https://couples.jp/robots.txt", status=404)
    responses.add(
        responses.GET, "https://couples.jp/hotel-details/67890", status=200, content_type="text/html",
        body="""
        <html><head><meta charset="utf-8">
        <link rel="canonical" href="https://couples.jp/hotel-details/67890"></head>
        <body><p>〒460-0001 愛知県名古屋市中区栄1-1-1</p></body></html>
        """,
    )
    jr = JobRegistry(db)
    job_id = make_lovehotel_job(jr, config={
        "seed_urls": ["https://couples.jp/hotel-details/67890"],
        "discovery": {"internal_links": False, "related_entities": False},
    })
    worker = Worker(app_config, worker_id="lovehotel-test-worker-2", db=db)
    for _ in range(2):
        jr.mark_queued(job_id)
        worker.run_one_job()

    review_rows = db.query(
        "SELECT * FROM review_queue WHERE job_id=? AND reason='missing_required_field'", (job_id,)
    )
    assert len(review_rows) == 1
    assert "name" in review_rows[0]["details"]


@responses.activate
def test_duplicate_across_urls_merges_via_facility_id(app_config, db):
    responses.add(responses.GET, "https://couples.jp/robots.txt", status=404)
    html = _facility_html(
        "https://couples.jp/hotel-details/12345", "ホテル アルファ", "150-0001", "東京都渋谷区神宮前1-2-3", "03-1111-2222",
    )
    responses.add(responses.GET, "https://couples.jp/hotel-details/12345", status=200, content_type="text/html", body=html)
    responses.add(
        responses.GET, "https://couples.jp/hotel-details/12345?ref=list", status=200, content_type="text/html", body=html,
    )
    jr = JobRegistry(db)
    job_id = make_lovehotel_job(jr, config={
        "seed_urls": [
            "https://couples.jp/hotel-details/12345",
            "https://couples.jp/hotel-details/12345?ref=list",
        ],
        "discovery": {"internal_links": False, "related_entities": False},
    })
    worker = Worker(app_config, worker_id="lovehotel-test-worker-3", db=db)
    for _ in range(3):
        jr.mark_queued(job_id)
        worker.run_one_job()

    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert len(entities) == 1  # merged, not duplicated
    assert entities[0]["external_id"] == "12345"

    run_rows = db.query("SELECT * FROM run_history WHERE job_id=?", (job_id,))
    assert sum(r["duplicate_count"] for r in run_rows) >= 1


@responses.activate
def test_same_name_different_address_is_never_auto_merged(app_config, db):
    """Two real facilities can share an exact name -- STEP 6 of this DB's
    brief is explicit that this must route to review, never silently
    collapse into one entity."""
    responses.add(responses.GET, "https://couples.jp/robots.txt", status=404)
    responses.add(
        responses.GET, "https://couples.jp/hotel-details/12345", status=200, content_type="text/html",
        body=_facility_html(
            "https://couples.jp/hotel-details/12345", "ホテル アルファ", "150-0001", "東京都渋谷区神宮前1-2-3", "03-1111-2222",
        ),
    )
    responses.add(
        responses.GET, "https://couples.jp/hotel-details/99999", status=200, content_type="text/html",
        body=_facility_html(
            "https://couples.jp/hotel-details/99999", "ホテル アルファ", "220-0001", "神奈川県横浜市西区北幸1-1-1",
            "045-555-6666",
        ),
    )
    jr = JobRegistry(db)
    job_id = make_lovehotel_job(jr, config={
        "seed_urls": ["https://couples.jp/hotel-details/12345", "https://couples.jp/hotel-details/99999"],
        "discovery": {"internal_links": False, "related_entities": False},
    })
    worker = Worker(app_config, worker_id="lovehotel-test-worker-4", db=db)
    for _ in range(3):
        jr.mark_queued(job_id)
        worker.run_one_job()

    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert len(entities) == 1  # the second one was NOT auto-merged nor auto-inserted as a plain new row

    review_rows = db.query(
        "SELECT * FROM review_queue WHERE job_id=? AND reason='duplicate_ambiguity'", (job_id,)
    )
    assert len(review_rows) == 1


@responses.activate
def test_retry_then_permanent_failure_does_not_block_other_facilities(app_config, db):
    responses.add(responses.GET, "https://couples.jp/robots.txt", status=404)
    responses.add(
        responses.GET, "https://couples.jp/hotel-details/12345", status=200, content_type="text/html",
        body=_facility_html(
            "https://couples.jp/hotel-details/12345", "ホテル アルファ", "150-0001", "東京都渋谷区神宮前1-2-3", "03-1111-2222",
        ),
    )
    responses.add(responses.GET, "https://couples.jp/hotel-details/down", status=503)
    responses.add(responses.GET, "https://couples.jp/hotel-details/down", status=503)

    jr = JobRegistry(db)
    job_id = make_lovehotel_job(jr, config={
        "seed_urls": ["https://couples.jp/hotel-details/12345", "https://couples.jp/hotel-details/down"],
        "discovery": {"internal_links": False, "related_entities": False},
    })
    ctx = CollectorContext.build(app_config, db)

    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    job = jr.get(job_id)
    collector = get_collector(job["collector_type"], ctx)
    collector.run_once(job)
    db.execute("UPDATE fetch_queue SET max_attempts=2 WHERE job_id=? AND url LIKE '%down%'", (job_id,))

    for _ in range(3):
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

    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert any(e["name"] == "ホテル アルファ" for e in entities)

    review_rows = db.query("SELECT * FROM review_queue WHERE job_id=? AND reason='parse_failure'", (job_id,))
    assert len(review_rows) >= 1


@responses.activate
def test_checkpoint_persists_across_simulated_restart(app_config, db):
    _mock_base_site()
    jr = JobRegistry(db)
    job_id = make_lovehotel_job(jr)
    worker = Worker(app_config, worker_id="lovehotel-test-worker-5", db=db)

    jr.mark_queued(job_id)
    worker.run_one_job()

    checkpoint = worker.ctx.checkpoints.load(job_id)
    assert checkpoint["state"].get("seeded") is True

    worker2 = Worker(app_config, worker_id="lovehotel-test-worker-5b", db=db)
    checkpoint2 = worker2.ctx.checkpoints.load(job_id)
    assert checkpoint2["state"].get("seeded") is True
