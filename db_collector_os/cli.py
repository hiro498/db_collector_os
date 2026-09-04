"""db-collector: production management CLI.

Examples:
    db-collector migrate
    db-collector jobs sync
    db-collector jobs reseed JOB_ID
    db-collector jobs list
    db-collector jobs run JOB_ID
    db-collector jobs pause JOB_ID
    db-collector jobs resume JOB_ID
    db-collector queue JOB_ID
    db-collector review list
    db-collector health
    db-collector integrity
    db-collector scheduler run [--once]
    db-collector worker run [--once]
    db-collector admin serve
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
import yaml

from .candidates import CandidateStore
from .checkpoint import CheckpointStore
from .collectors import CollectorContext
from .collectors.pipeline import ensure_seed_urls_queued
from .config import AppConfig, load_config
from .database import Database
from .fetching import FetchQueue
from .job_registry import JobRegistry
from .logging_config import get_logger
from .metrics import MetricsStore
from .models.enums import JobStatus
from .resource_controller import ResourceController
from .review import ReviewQueue
from .run_history import RunHistoryStore
from .scheduler import Scheduler
from .worker import Worker, run_job_and_record


@click.group()
@click.option("--config", "config_path", default=None, help="Path to config YAML (default: config/default.yaml)")
@click.pass_context
def main(ctx: click.Context, config_path: str | None) -> None:
    """DB Collector OS management CLI."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path)


def _db(ctx: click.Context) -> Database:
    return Database(ctx.obj["config"].db_path)


# --------------------------------------------------------------------------
# migrate / integrity / health / status
# --------------------------------------------------------------------------

@main.command()
@click.pass_context
def migrate(ctx: click.Context) -> None:
    """Apply pending database migrations."""
    db = _db(ctx)
    ok, result = db.integrity_check()
    click.echo(f"migrations applied. integrity_check={result}")


@main.command()
@click.pass_context
def integrity(ctx: click.Context) -> None:
    """Run PRAGMA integrity_check against the SQLite database."""
    db = _db(ctx)
    ok, result = db.integrity_check()
    click.echo(result)
    sys.exit(0 if ok else 1)


@main.command()
@click.pass_context
def health(ctx: click.Context) -> None:
    """Report scheduler/worker/db/disk/queue/stale-job health as JSON."""
    config: AppConfig = ctx.obj["config"]
    db = _db(ctx)
    jobs = JobRegistry(db)
    fetch_queue = FetchQueue(db)
    review = ReviewQueue(db)
    resources = ResourceController(config.resource_thresholds)

    ok, integ = db.integrity_check()
    snap = resources.snapshot()
    workers = db.query("SELECT * FROM workers ORDER BY last_heartbeat DESC LIMIT 10")
    stale_jobs = db.query(
        "SELECT job_id, job_name, last_started_at FROM jobs WHERE status='running' "
        "AND last_started_at IS NOT NULL AND last_started_at < datetime('now', ?)",
        (f"-{int(config.worker_stale_seconds)} seconds",),
    )
    recent_errors = db.query(
        "SELECT COUNT(*) AS n FROM run_history WHERE started_at > datetime('now','-1 day') AND error_count > 0"
    )

    report = {
        "db_integrity_ok": ok,
        "db_integrity_detail": integ,
        "resources": snap.as_dict(),
        "jobs_total": len(jobs.list()),
        "jobs_running": len(jobs.list(status=JobStatus.RUNNING)),
        "jobs_failed": len(jobs.list(status=JobStatus.FAILED)),
        "review_open": review.count_open(),
        "workers": workers,
        "stale_jobs": stale_jobs,
        "recent_runs_with_errors_24h": recent_errors[0]["n"] if recent_errors else 0,
    }
    click.echo(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    healthy = ok and not stale_jobs
    sys.exit(0 if healthy else 1)


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Top-level status summary (mirrors the Admin UI top page)."""
    db = _db(ctx)
    jobs = JobRegistry(db)
    review = ReviewQueue(db)
    metrics = MetricsStore(db)
    today = metrics.today()

    summary = {
        "jobs_total": len(jobs.list()),
        "jobs_active": len(jobs.list(enabled_only=True)),
        "jobs_queued": len(jobs.list(status=JobStatus.QUEUED)),
        "jobs_running": len(jobs.list(status=JobStatus.RUNNING)),
        "jobs_completed": len(jobs.list(status=JobStatus.COMPLETED)),
        "jobs_failed": len(jobs.list(status=JobStatus.FAILED)),
        "review_open": review.count_open(),
        "today_new_entities": today["new_entities"],
        "today_updated_entities": today["updated_entities"],
        "today_fetch_errors": today["fetch_errors"],
    }
    click.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@main.command("lovehotel-status")
@click.option("--job-id", default=None, help="Defaults to job_prod_lovehotel_couples")
@click.pass_context
def lovehotel_status(ctx: click.Context, job_id: str | None) -> None:
    """全国ラブホテルDB status summary (mirrors the Admin UI's dashboard
    section -- both call `lovehotel_audit.lovehotel_summary`, read-only)."""
    from .lovehotel_audit import LOVEHOTEL_JOB_ID, lovehotel_summary

    db = _db(ctx)
    summary = lovehotel_summary(db, job_id or LOVEHOTEL_JOB_ID)
    click.echo(json.dumps(summary, indent=2, ensure_ascii=False, default=str))


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------

@main.group()
def jobs() -> None:
    """Manage jobs."""


@jobs.command("sync")
@click.pass_context
def jobs_sync(ctx: click.Context) -> None:
    """Load/upsert job definitions from config/jobs/*.yaml into the registry."""
    config: AppConfig = ctx.obj["config"]
    db = _db(ctx)
    registry = JobRegistry(db)
    jobs_dir = config.jobs_dir
    count = 0
    for path in sorted(jobs_dir.glob("*.yaml")) + sorted(jobs_dir.glob("*.yml")):
        with open(path, encoding="utf-8") as fh:
            spec = yaml.safe_load(fh) or {}
        job_id = registry.create(
            job_id=spec.get("job_id"),
            job_name=spec["job_name"],
            category=spec["category"],
            target_db=spec.get("target_db", spec["category"]),
            target_table=spec.get("target_table", "entities"),
            collector_type=spec["collector_type"],
            adapter=spec["adapter"],
            priority=spec.get("priority", 50),
            enabled=spec.get("enabled", True),
            schedule=spec.get("schedule", "@hourly"),
            max_pages=spec.get("max_pages", 200),
            max_depth=spec.get("max_depth", 3),
            concurrency=spec.get("concurrency", 2),
            rate_limit=spec.get("rate_limit", 1.0),
            config=spec.get("config", {}),
        )
        click.echo(f"synced {path.name} -> {job_id}")
        count += 1
    click.echo(f"{count} job definition(s) synced")


@jobs.command("reseed")
@click.argument("job_id")
@click.pass_context
def jobs_reseed(ctx: click.Context, job_id: str) -> None:
    """Idempotently enqueue this job's CURRENT config_json.seed_urls into
    fetch_queue, synchronously, from this process. Complements (does not
    replace) the same guarantee `run_once()` performs on every worker
    tick -- run this right after `jobs sync` (which is what
    scripts/run_goodsmile_phase1_batch1.sh does) so a config-added seed
    reaches the queue immediately, without depending on whether/when the
    long-running worker process has reloaded code that includes this
    logic. Never duplicates or force-refetches an already-tracked URL
    (fetch_queue.enqueue() is idempotent per (job_id, url), any status
    including 'done').
    """
    config: AppConfig = ctx.obj["config"]
    db = _db(ctx)
    registry = JobRegistry(db)
    job = registry.get(job_id)
    if not job:
        click.echo(f"no such job: {job_id}", err=True)
        sys.exit(1)
    ctx_obj = CollectorContext.build(config, db)
    newly_queued = ensure_seed_urls_queued(ctx_obj, job)
    click.echo(json.dumps(
        {"job_id": job_id, "newly_queued_count": len(newly_queued), "newly_queued": newly_queued},
        indent=2,
    ))


@jobs.command("list")
@click.option("--status", "status_filter", default=None)
@click.pass_context
def jobs_list(ctx: click.Context, status_filter: str | None) -> None:
    db = _db(ctx)
    registry = JobRegistry(db)
    for job in registry.list(status=status_filter):
        click.echo(
            f"{job['job_id']:36} {job['job_name']:30} type={job['collector_type']:16} "
            f"phase={job['phase']:16} status={job['status']:10} priority={job['priority']:3} "
            f"next_run={job['next_run_at']}"
        )


@jobs.command("run")
@click.argument("job_id")
@click.pass_context
def jobs_run(ctx: click.Context, job_id: str) -> None:
    """Run a job synchronously, once, in this process (for manual/testing use)."""
    config: AppConfig = ctx.obj["config"]
    db = _db(ctx)
    registry = JobRegistry(db)
    job = registry.get(job_id)
    if not job:
        click.echo(f"no such job: {job_id}", err=True)
        sys.exit(1)
    registry.mark_queued(job_id)
    if not registry.claim_queued(job_id):
        click.echo(f"could not claim job {job_id} (status={job['status']})", err=True)
        sys.exit(1)
    job = registry.get(job_id)
    ctx_obj = CollectorContext.build(config, db)
    outcome, status = run_job_and_record(ctx_obj, registry, job, config.worker_poll_interval_seconds)
    if outcome is None:
        click.echo(json.dumps({"status": status, "error": "job raised an exception -- see logs/worker.log"}, indent=2))
        sys.exit(1)
    click.echo(json.dumps({"status": status, **outcome.as_kwargs()}, indent=2))


@jobs.command("pause")
@click.argument("job_id")
@click.pass_context
def jobs_pause(ctx: click.Context, job_id: str) -> None:
    JobRegistry(_db(ctx)).pause(job_id)
    click.echo(f"paused {job_id}")


@jobs.command("resume")
@click.argument("job_id")
@click.pass_context
def jobs_resume(ctx: click.Context, job_id: str) -> None:
    JobRegistry(_db(ctx)).resume(job_id)
    click.echo(f"resumed {job_id}")


@jobs.command("enable")
@click.argument("job_id")
@click.pass_context
def jobs_enable(ctx: click.Context, job_id: str) -> None:
    """Flip a job's `enabled` flag on (it still needs status
    idle/completed/continuing/retry -- see `jobs resume` -- to actually
    become due)."""
    registry = JobRegistry(_db(ctx))
    if not registry.get(job_id):
        click.echo(f"no such job: {job_id}", err=True)
        sys.exit(1)
    registry.set_enabled(job_id, True)
    click.echo(f"enabled {job_id}")


@jobs.command("disable")
@click.argument("job_id")
@click.pass_context
def jobs_disable(ctx: click.Context, job_id: str) -> None:
    """Flip a job's `enabled` flag off. Does not stop an already-running run."""
    registry = JobRegistry(_db(ctx))
    if not registry.get(job_id):
        click.echo(f"no such job: {job_id}", err=True)
        sys.exit(1)
    registry.set_enabled(job_id, False)
    click.echo(f"disabled {job_id}")


@jobs.command("show")
@click.argument("job_id")
@click.pass_context
def jobs_show(ctx: click.Context, job_id: str) -> None:
    db = _db(ctx)
    job = JobRegistry(db).get(job_id)
    if not job:
        click.echo("not found", err=True)
        sys.exit(1)
    click.echo(json.dumps(job, indent=2, ensure_ascii=False, default=str))


# --------------------------------------------------------------------------
# queue / review / checkpoint
# --------------------------------------------------------------------------

@main.command()
@click.argument("job_id", required=False)
@click.pass_context
def queue(ctx: click.Context, job_id: str | None) -> None:
    """Show fetch queue stats for a job (or all jobs)."""
    db = _db(ctx)
    fq = FetchQueue(db)
    if job_id:
        click.echo(json.dumps(fq.stats(job_id), indent=2))
    else:
        rows = db.query("SELECT job_id, status, COUNT(*) AS n FROM fetch_queue GROUP BY job_id, status")
        click.echo(json.dumps(rows, indent=2, default=str))


@main.group(invoke_without_command=True)
@click.pass_context
def review(ctx: click.Context) -> None:
    """Review queue operations."""
    if ctx.invoked_subcommand is None:
        db = _db(ctx)
        rq = ReviewQueue(db)
        for item in rq.list_open():
            click.echo(f"#{item['review_id']:6} job={item['job_id']} reason={item['reason']:24} details={item['details']}")


@review.command("resolve")
@click.argument("review_id", type=int)
@click.pass_context
def review_resolve(ctx: click.Context, review_id: int) -> None:
    ReviewQueue(_db(ctx)).resolve(review_id)
    click.echo(f"resolved review #{review_id}")


# --------------------------------------------------------------------------
# scheduler / worker / admin
# --------------------------------------------------------------------------

@main.group()
def scheduler() -> None:
    """Scheduler process."""


@scheduler.command("run")
@click.option("--once", is_flag=True, help="Run a single tick and exit (for smoke tests).")
@click.pass_context
def scheduler_run(ctx: click.Context, once: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    sched = Scheduler(config)
    if once:
        n = sched.tick()
        click.echo(f"queued {n} job(s)")
    else:
        sched.run_forever()


@main.group()
def worker() -> None:
    """Worker process."""


@worker.command("run")
@click.option("--once", is_flag=True, help="Process at most one queued job and exit (for smoke tests).")
@click.pass_context
def worker_run(ctx: click.Context, once: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    worker_id = os.environ.get("DB_COLLECTOR_WORKER_ID")
    w = Worker(config, worker_id=worker_id)
    if once:
        did_work = w.run_one_job()
        click.echo(f"processed a job: {did_work}")
    else:
        w.run_forever()


@main.group()
def admin() -> None:
    """Admin UI process."""


@admin.command("serve")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
@click.pass_context
def admin_serve(ctx: click.Context, host: str | None, port: int | None) -> None:
    import uvicorn

    from .admin.app import create_app

    config: AppConfig = ctx.obj["config"]
    app = create_app(config)
    uvicorn.run(app, host=host or config.admin_host, port=port or config.admin_port)


if __name__ == "__main__":
    main()
