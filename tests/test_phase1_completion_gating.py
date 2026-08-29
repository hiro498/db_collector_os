"""Regression tests for ISSUE 3 (premature Phase 1 completion): a job must
never reach JobPhase.PHASE1_COMPLETE just because `min_entity_count` was
satisfied by a single already-known entity -- discovery must have actually
run and genuinely tapered off (discovery/saturation.py's fix: a
discovered_total of 0 is "never tried", not "saturated").
"""

from __future__ import annotations

import responses

from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType, JobPhase
from db_collector_os.worker import Worker
from tests.test_goodsmile_phase1_pipeline_integration import _make_job, _mock_site

PRODUCT_URL = (
    "https://www.goodsmile.com/en/product/1141716/"
    "Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2Btoridamono"
)


@responses.activate
def test_single_seed_with_no_discovery_never_reaches_phase1_complete(app_config, db):
    """A job seeded with exactly one product page and discovery explicitly
    disabled has nothing to discover, ever -- min_entity_count=1 is
    trivially satisfied by that one entity, but require_discovery_saturation
    must keep blocking completion since discovery never actually ran
    (discovered_total stays 0 forever). This must not "complete" Phase 1.
    """
    responses.add(responses.GET, "https://www.goodsmile.com/robots.txt", status=404)
    responses.add(
        responses.GET, PRODUCT_URL, status=200, content_type="text/html",
        body='<html><head><title>P</title><script type="application/ld+json">'
             '{"@type":"Product","name":"Widget","sku":"1141716"}</script></head>'
             '<body><h1>Widget</h1></body></html>',
    )

    jr = JobRegistry(db)
    job_id = jr.create(
        job_name="single seed, no discovery", category="figure", target_db="figure_official_site_test",
        target_table="entities", collector_type=CollectorType.OFFICIAL_SITE, adapter="figure_official_site",
        rate_limit=0.0, max_pages=10,
        config={
            "seed_urls": [PRODUCT_URL],
            "discovery": {"internal_links": False, "related_entities": False},
            "phase1_conditions": {
                "queue_empty": True, "require_discovery_saturation": True,
                "consecutive_low_discovery_runs": 3, "min_entity_count": 1,
            },
        },
    )
    worker = Worker(app_config, worker_id="gating-test-worker", db=db)
    for _ in range(10):
        jr.mark_queued(job_id)
        worker.run_one_job()

    job = jr.get(job_id)
    assert job["phase"] != JobPhase.PHASE1_COMPLETE
    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert len(entities) == 1  # the one entity exists...
    # ...but that alone must never be treated as "Phase 1 done".


@responses.activate
def test_genuine_discovery_saturation_does_reach_phase1_complete(app_config, db):
    """The positive case: a job that DOES run real discovery (the Good
    Smile list page + its product links) and eventually exhausts what
    there is to find must still be able to progress all the way to
    PHASE1_COMPLETE -- the zero-discovered_total fix must not make every
    job stall forever.
    """
    _mock_site()
    jr = JobRegistry(db)
    job_id = _make_job(jr)
    worker = Worker(app_config, worker_id="gating-test-worker-2", db=db)

    reached_complete = False
    for _ in range(20):
        # A couple of fetches in this mocked run legitimately fail (see
        # _mock_site()); skip their real-time exponential backoff so the
        # queue can actually reach empty within this fast-running test,
        # exactly like tests/test_figure_pipeline_integration.py's own
        # retry test does.
        db.execute("UPDATE fetch_queue SET next_retry_at=NULL WHERE job_id=? AND status='queued'", (job_id,))
        jr.mark_queued(job_id)
        worker.run_one_job()
        if jr.get(job_id)["phase"] == JobPhase.PHASE1_COMPLETE:
            reached_complete = True
            break

    assert reached_complete, f"expected PHASE1_COMPLETE within 20 ticks, got {jr.get(job_id)['phase']}"
    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert len(entities) > 1  # real population growth happened, not just one seed entity
