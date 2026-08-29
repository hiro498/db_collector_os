from __future__ import annotations

from datetime import datetime, timedelta, timezone

import responses

from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType, JobStatus
from db_collector_os.worker import Worker


def make_job(jr: JobRegistry, **overrides) -> str:
    defaults = dict(
        job_name="Test Job", category="product", target_db="products", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="sample_official_site",
        config={"seed_urls": ["https://shop.example.com/product/1"]},
    )
    defaults.update(overrides)
    return jr.create(**defaults)


@responses.activate
def test_run_one_job_processes_queued_job(app_config, db):
    responses.add(responses.GET, "https://shop.example.com/robots.txt", status=404)
    responses.add(
        responses.GET, "https://shop.example.com/product/1", status=200, content_type="text/html",
        body='<html><head><title>P</title><script type="application/ld+json">'
             '{"@type":"Product","name":"Widget"}</script></head><body><h1>Widget</h1></body></html>',
    )

    jr = JobRegistry(db)
    job_id = make_job(jr)
    jr.mark_queued(job_id)

    worker = Worker(app_config, worker_id="test-worker", db=db)
    did_work = worker.run_one_job()
    assert did_work is True

    job = jr.get(job_id)
    # COMPLETED (queue drained, Phase 1 conditions satisfied) or CONTINUING
    # (healthy, more work queued/discovery-saturation not yet confirmed) --
    # never RETRY, which means an actual failure (see JobStatus.CONTINUING).
    assert job["status"] in (JobStatus.COMPLETED, JobStatus.CONTINUING)

    run_rows = db.query("SELECT * FROM run_history WHERE job_id=?", (job_id,))
    assert len(run_rows) == 1
    assert run_rows[0]["status"] == "completed"


def test_run_one_job_returns_false_when_nothing_queued(app_config, db):
    worker = Worker(app_config, worker_id="test-worker", db=db)
    assert worker.run_one_job() is False


def test_worker_isolates_job_failure(app_config, db, monkeypatch):
    jr = JobRegistry(db)
    job_id = make_job(jr)
    jr.mark_queued(job_id)

    worker = Worker(app_config, worker_id="test-worker", db=db)

    def boom(*_args, **_kwargs):
        raise RuntimeError("adapter exploded")

    import db_collector_os.collectors.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module.BaseCollector, "run_once", boom)

    did_work = worker.run_one_job()
    assert did_work is True
    job = jr.get(job_id)
    assert job["status"] == JobStatus.FAILED  # failed job, but worker itself kept running


def test_recover_stale_jobs_resets_dead_worker_jobs(app_config, db):
    jr = JobRegistry(db)
    job_id = make_job(jr)
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    # backdate last_started_at well past the stale threshold
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=app_config.worker_stale_seconds * 2)).isoformat(timespec="seconds")
    db.execute("UPDATE jobs SET last_started_at=? WHERE job_id=?", (stale_time, job_id))

    worker = Worker(app_config, worker_id="test-worker", db=db)
    n = worker.recover_stale_jobs()
    assert n == 1
    assert jr.get(job_id)["status"] == JobStatus.RETRY


def test_worker_registers_and_heartbeats(app_config, db):
    worker = Worker(app_config, worker_id="hb-test-worker", db=db)
    row = db.query_one("SELECT * FROM workers WHERE worker_id=?", ("hb-test-worker",))
    assert row is not None
    assert row["status"] == "idle"
