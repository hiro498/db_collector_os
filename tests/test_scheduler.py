from __future__ import annotations

from db_collector_os.job_registry import JobRegistry
from db_collector_os.scheduler import Scheduler


def make_job(jr: JobRegistry, **overrides) -> str:
    defaults = dict(
        job_name="Test Job", category="product", target_db="products", target_table="entities",
        collector_type="official_site", adapter="sample_official_site",
    )
    defaults.update(overrides)
    return jr.create(**defaults)


def test_tick_queues_due_jobs(app_config, db):
    jr = JobRegistry(db)
    job_id = make_job(jr, priority=90)
    sched = Scheduler(app_config, db=db)
    n = sched.tick()
    assert n == 1
    assert jr.get(job_id)["status"] == "queued"


def test_tick_skips_disabled_jobs(app_config, db):
    jr = JobRegistry(db)
    make_job(jr, enabled=False)
    sched = Scheduler(app_config, db=db)
    assert sched.tick() == 0


def test_tick_respects_resource_controller(app_config, db, monkeypatch):
    jr = JobRegistry(db)
    make_job(jr)
    sched = Scheduler(app_config, db=db)
    monkeypatch.setattr(sched.resources, "can_admit_new_job", lambda: (False, "cpu too high"))
    n = sched.tick()
    assert n == 0
    assert jr.list(status="queued") == []


def test_tick_admits_multiple_jobs_by_priority(app_config, db):
    jr = JobRegistry(db)
    low = make_job(jr, priority=10)
    high = make_job(jr, priority=90)
    sched = Scheduler(app_config, db=db)
    n = sched.tick()
    assert n == 2
    due = jr.list(status="queued")
    assert due[0]["job_id"] == high  # highest priority first
