from __future__ import annotations

from db_collector_os.job_registry import JobRegistry, compute_next_run
from db_collector_os.models.enums import JobPhase, JobStatus


def make_job(jr: JobRegistry, **overrides) -> str:
    defaults = dict(
        job_name="Test Job", category="product", target_db="products", target_table="entities",
        collector_type="official_site", adapter="sample_official_site",
    )
    defaults.update(overrides)
    return jr.create(**defaults)


def test_compute_next_run_named_intervals():
    assert compute_next_run("@hourly") > compute_next_run("@minutely")


def test_compute_next_run_every_syntax():
    from datetime import datetime, timezone
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = compute_next_run("@every 30s", base=base)
    assert result == "2026-01-01T00:00:30+00:00"


def test_create_and_get(db):
    jr = JobRegistry(db)
    job_id = make_job(jr)
    job = jr.get(job_id)
    assert job["job_name"] == "Test Job"
    assert job["phase"] == JobPhase.BOOTSTRAP
    assert job["status"] == JobStatus.IDLE
    assert job["enabled"] is True


def test_create_is_upsert(db):
    jr = JobRegistry(db)
    job_id = make_job(jr, job_id="fixed_id", priority=10)
    make_job(jr, job_id="fixed_id", priority=99)
    job = jr.get(job_id)
    assert job["priority"] == 99
    assert len(jr.list()) == 1


def test_set_enabled_then_resync_reverts_to_yaml_value(db):
    """Documents an operational trap: `create()` (used by `jobs sync`) always
    writes `enabled` from its argument (ON CONFLICT ... enabled=excluded.enabled).
    So a manual `jobs enable` survives until the next `jobs sync` re-applies
    whatever the YAML file currently says -- the YAML is the durable source
    of truth for `enabled`, not the DB. Deployment scripts must account for
    this ordering (sync, then enable -- not the other way around, or re-sync
    the YAML with enabled: true baked in).
    """
    jr = JobRegistry(db)
    job_id = make_job(jr, job_id="resync_test", enabled=False)
    jr.set_enabled(job_id, True)
    assert jr.get(job_id)["enabled"] is True

    make_job(jr, job_id="resync_test", enabled=False)  # simulates a re-sync from YAML
    assert jr.get(job_id)["enabled"] is False


def test_due_jobs_respects_enabled_and_schedule(db):
    jr = JobRegistry(db)
    disabled = make_job(jr, enabled=False)
    enabled = make_job(jr, enabled=True)
    due_ids = {j["job_id"] for j in jr.due_jobs()}
    assert enabled in due_ids
    assert disabled not in due_ids


def test_claim_queued_is_atomic(db):
    jr = JobRegistry(db)
    job_id = make_job(jr)
    jr.mark_queued(job_id)
    assert jr.claim_queued(job_id) is True
    # already running -> cannot claim twice
    assert jr.claim_queued(job_id) is False


def test_pause_resume(db):
    jr = JobRegistry(db)
    job_id = make_job(jr)
    jr.pause(job_id)
    assert jr.get(job_id)["status"] == JobStatus.PAUSED
    assert job_id not in {j["job_id"] for j in jr.due_jobs()}  # paused jobs are never due
    jr.resume(job_id)
    assert jr.get(job_id)["status"] == JobStatus.IDLE
    assert jr.get(job_id)["next_run_at"] is not None


def test_finish_sets_next_run_from_schedule(db):
    jr = JobRegistry(db)
    job_id = make_job(jr, schedule="@every 60s")
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    jr.finish(job_id, JobStatus.COMPLETED)
    job = jr.get(job_id)
    assert job["status"] == JobStatus.COMPLETED
    assert job["next_run_at"] is not None


def test_reset_stale_running(db):
    jr = JobRegistry(db)
    job_id = make_job(jr)
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    jr.reset_stale_running(job_id)
    assert jr.get(job_id)["status"] == JobStatus.RETRY
