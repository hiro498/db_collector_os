"""Regression tests for the Good Smile Phase 1 Batch #2 lifecycle bug: a
successful run (run_history.status=completed, error_count=0) with more
work left to do was being labeled job.status=retry, indistinguishable from
a real failure being retried. Introduces JobStatus.CONTINUING for the
healthy case and reserves RETRY for genuine failure/crash-recovery only.
"""

from __future__ import annotations

import responses

from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType, JobStatus
from db_collector_os.worker import Worker


def make_job(jr: JobRegistry, **overrides) -> str:
    defaults = dict(
        job_name="Continuing Status Test", category="product", target_db="products", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="sample_official_site",
        rate_limit=0.0,
        config={"seed_urls": ["https://shop.example.com/product/1"]},
    )
    defaults.update(overrides)
    return jr.create(**defaults)


def _page(name: str) -> str:
    return (
        '<html><head><title>P</title><script type="application/ld+json">'
        f'{{"@type":"Product","name":"{name}"}}</script></head><body><h1>{name}</h1></body></html>'
    )


# -- item 1 + 2: successful run with queue remaining -> CONTINUING, not RETRY --


@responses.activate
def test_successful_run_with_remaining_queue_is_continuing_not_retry(app_config, db):
    urls = [f"https://shop.example.com/product/{i}" for i in range(3)]
    jr = JobRegistry(db)
    job_id = make_job(jr, max_pages=1, config={  # max_pages=1 guarantees queue remains after one run_once()
        "seed_urls": urls,
        "discovery": {"internal_links": False, "related_entities": False},
    })

    responses.add(responses.GET, "https://shop.example.com/robots.txt", status=404)
    for i, url in enumerate(urls):
        responses.add(responses.GET, url, status=200, content_type="text/html", body=_page(f"W{i}"))

    jr.mark_queued(job_id)
    worker = Worker(app_config, worker_id="continuing-test-worker", db=db)
    worker.run_one_job()

    job = jr.get(job_id)
    run = db.query_one(
        "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1", (job_id,)
    )
    assert run["status"] == "completed"
    assert run["fetched_count"] > 0
    assert run["inserted_count"] > 0
    assert run["error_count"] == 0

    # the actual bug: this run succeeded and there's still queue left --
    # that must never be reported as job.status=retry.
    assert job["status"] != JobStatus.RETRY
    assert job["status"] == JobStatus.CONTINUING
    assert not db.query_one("SELECT 1 AS x FROM fetch_queue WHERE job_id=? AND status='queued'", (job_id,)) is None


# -- item 3: Phase 1 not yet saturated (queue empty) -> CONTINUING, not RETRY, --
# -- and scheduled again soon rather than waiting for the full @daily cadence --


@responses.activate
def test_phase1_not_saturated_continues_soon_not_retry(app_config, db):
    responses.add(responses.GET, "https://shop.example.com/robots.txt", status=404)
    responses.add(
        responses.GET, "https://shop.example.com/product/1", status=200, content_type="text/html", body=_page("W"),
    )

    jr = JobRegistry(db)
    job_id = make_job(jr, schedule="@daily", config={
        "seed_urls": ["https://shop.example.com/product/1"],
        "discovery": {"internal_links": False, "related_entities": False},
        "phase1_conditions": {
            "queue_empty": True, "require_discovery_saturation": True,
            "consecutive_low_discovery_runs": 3, "min_entity_count": 1,
        },
    })

    jr.mark_queued(job_id)
    worker = Worker(app_config, worker_id="saturation-continue-worker", db=db)
    worker.run_one_job()

    job = jr.get(job_id)
    assert job["status"] != JobStatus.RETRY
    assert job["status"] == JobStatus.CONTINUING
    # scheduled again soon (worker_poll_interval_seconds-ish), NOT the full
    # @daily interval -- otherwise saturation confirmation would take days.
    from datetime import datetime, timezone
    next_run = datetime.fromisoformat(job["next_run_at"])
    assert (next_run - datetime.now(timezone.utc)).total_seconds() < 3600


# -- item 4: a genuine crash/failure still uses RETRY (unchanged meaning) --


def test_genuine_crash_recovery_still_uses_retry(app_config, db):
    from datetime import datetime, timedelta, timezone

    jr = JobRegistry(db)
    job_id = make_job(jr)
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=app_config.worker_stale_seconds * 2)).isoformat(
        timespec="seconds"
    )
    db.execute("UPDATE jobs SET last_started_at=? WHERE job_id=?", (stale_time, job_id))

    worker = Worker(app_config, worker_id="crash-recovery-worker", db=db)
    n = worker.recover_stale_jobs()
    assert n == 1
    assert jr.get(job_id)["status"] == JobStatus.RETRY


# -- item: job never ends in the enabled=false + status=retry contradiction --


@responses.activate
def test_disabled_job_is_never_left_as_retry(app_config, db):
    """A job that gets disabled (e.g. by a batch watcher) must never be
    left showing status=retry -- that specifically implies "a failed run
    is waiting to be retried", which is misleading for a job that was
    deliberately stopped. Mirrors what scripts/_phase1_batch1_watch_and_
    report.sh / batch2's watcher do: `jobs disable` after the batch.
    """
    jr = JobRegistry(db)
    job_id = make_job(jr, max_pages=1, config={
        "seed_urls": [f"https://shop.example.com/product/{i}" for i in range(2)],
        "discovery": {"internal_links": False, "related_entities": False},
    })
    responses.add(responses.GET, "https://shop.example.com/robots.txt", status=404)
    responses.add(responses.GET, "https://shop.example.com/product/0", status=200, content_type="text/html", body=_page("W0"))
    responses.add(responses.GET, "https://shop.example.com/product/1", status=200, content_type="text/html", body=_page("W1"))

    jr.mark_queued(job_id)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(rsps.GET, "https://shop.example.com/robots.txt", status=404)
        rsps.add(rsps.GET, "https://shop.example.com/product/0", status=200, content_type="text/html", body=_page("W0"))
        worker = Worker(app_config, worker_id="disable-test-worker", db=db)
        worker.run_one_job()

    assert jr.get(job_id)["status"] == JobStatus.CONTINUING  # confirms the bug scenario is reproduced

    jr.set_enabled(job_id, False)
    job = jr.get(job_id)
    assert job["enabled"] is False
    assert job["status"] != JobStatus.RETRY, "disabled job must never be left showing status=retry"
