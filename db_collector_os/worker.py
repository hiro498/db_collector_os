"""Worker: claims queued jobs, runs one bounded pipeline pass (via the
matching Collector), and updates run history / checkpoints / job status.

Designed for VPS-reboot resilience: `recover_stale_jobs()` resets jobs whose
worker died mid-run (heartbeat/last_started_at older than the stale
threshold) back to `retry`, so `checkpoint.py` state (fetch-queue rows,
candidate status, run counters already committed) picks up where it left
off instead of restarting the job from scratch.
"""

from __future__ import annotations

import os
import signal
import socket
import time
from datetime import datetime, timedelta, timezone

from .collectors import CollectorContext, RunOutcome, get_collector
from .config import AppConfig
from .database import Database
from .job_registry import JobRegistry, now_iso, now_plus
from .logging_config import get_logger
from .models.enums import JobPhase, JobStatus, RunStatus


def run_job_and_record(
    ctx: CollectorContext, jobs: JobRegistry, job: dict, poll_interval_seconds: float = 5.0, logger=None,
) -> tuple[RunOutcome | None, str]:
    """Run one collector pass for `job` (already claimed into 'running') and
    durably record the outcome: finishes the run_history row (completed or
    failed, with finished_at/duration_seconds/counts set), clears the
    in-flight checkpoint run_id, and updates the job's status/phase/
    next_run_at.

    This is the single source of truth for "what happens after run_once()"
    -- both Worker.run_one_job() (the systemd-run production path) and the
    `db-collector jobs run` CLI command call it, so a run's bookkeeping can
    never drift between the two call sites again (see the run_history bug
    from the first production proof, where the CLI path called run_once()
    directly and never finished the run_history row).

    Returns (outcome, status); outcome is None if the collector raised.
    """
    job_id = job["job_id"]
    try:
        collector = get_collector(job["collector_type"], ctx)
        outcome = collector.run_once(job)
    except Exception as exc:  # per-job isolation: one job's failure never kills the caller
        if logger:
            logger.exception("job %s failed: %s", job_id, exc)
        checkpoint = ctx.checkpoints.load(job_id)
        state = checkpoint["state"]
        run_id = state.get("current_run_id")
        existing_run = ctx.run_history.get(run_id) if run_id else None
        if not existing_run or existing_run["status"] != RunStatus.RUNNING:
            # Either the failure happened before run_once() reached
            # run_history.start() (e.g. an unresolvable adapter name), or
            # current_run_id was stale/already-finalized -- either way,
            # run_history is immutable execution history, so this failure
            # gets its own fresh row rather than touching an old one.
            run_id = ctx.run_history.start(job_id)
        ctx.run_history.finish(run_id, RunStatus.FAILED, error_count=1)
        state.pop("current_run_id", None)
        ctx.checkpoints.save(job_id, None, checkpoint["phase"] or job.get("phase"), state)
        jobs.finish(job_id, JobStatus.FAILED)
        return None, JobStatus.FAILED

    job_after = jobs.get(job_id)
    checkpoint = ctx.checkpoints.load(job_id)
    state = checkpoint["state"]
    run_id = state.get("current_run_id")

    # "More work to do" has two distinct, both entirely healthy, shapes:
    #  1. fetch_queue still has pending items for this job.
    #  2. Phase 1 hasn't been given a fair chance to judge discovery
    #     saturation yet (see discovery/saturation.py + phase_manager.py):
    #     the queue can look empty between discovery cycles while more
    #     low-yield discovery runs are still needed to confirm saturation
    #     -- without this, such a job would only get re-evaluated on its
    #     full `schedule` cadence (e.g. once a day), taking days to
    #     accumulate the few consecutive confirmations Phase 1 needs.
    # Neither of these is a failure -- see JobStatus.CONTINUING.
    phase1_conditions = (job_after.get("config_json", {}) or {}).get("phase1_conditions", {}) or {}
    required_streak = phase1_conditions.get("consecutive_low_discovery_runs", 0)
    low_streak = state.get("low_discovery_streak", 0)
    needs_more_discovery_runs = (
        job_after["phase"] in (JobPhase.DISCOVERY, JobPhase.COLLECT, JobPhase.VALIDATION)
        and bool(required_streak)
        and low_streak < required_streak
    )
    queue_has_work = job_after["phase"] != JobPhase.INCREMENTAL and not ctx.fetch_queue.is_empty(job_id)
    still_working = queue_has_work or needs_more_discovery_runs

    if run_id:
        ctx.run_history.finish(run_id, RunStatus.COMPLETED, **outcome.as_kwargs())
    state.pop("current_run_id", None)
    ctx.checkpoints.save(job_id, None, job_after["phase"], state)

    if still_working:
        jobs.finish(job_id, JobStatus.CONTINUING, next_run_override=now_plus(poll_interval_seconds))
        status = JobStatus.CONTINUING
    else:
        jobs.finish(job_id, JobStatus.COMPLETED)
        status = JobStatus.COMPLETED

    return outcome, status


class Worker:
    def __init__(self, config: AppConfig, worker_id: str | None = None, db: Database | None = None):
        self.config = config
        self.db = db or Database(config.db_path)
        self.jobs = JobRegistry(self.db)
        self.ctx = CollectorContext.build(config, self.db)
        self.logger = get_logger("worker", config.log_dir, config.log_level)
        self.worker_id = worker_id or f"worker-{socket.gethostname()}-{os.getpid()}"
        self._stop = False
        self._register()

    def request_stop(self, *_args) -> None:
        self.logger.info("graceful shutdown requested")
        self._stop = True

    def _register(self) -> None:
        self.db.execute(
            """INSERT INTO workers (worker_id, hostname, pid, status, started_at, last_heartbeat)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(worker_id) DO UPDATE SET status='idle', last_heartbeat=excluded.last_heartbeat""",
            (self.worker_id, socket.gethostname(), os.getpid(), "idle", now_iso(), now_iso()),
        )

    def _heartbeat(self, status: str, current_job_id: str | None) -> None:
        self.db.execute(
            "UPDATE workers SET status=?, current_job_id=?, last_heartbeat=? WHERE worker_id=?",
            (status, current_job_id, now_iso(), self.worker_id),
        )

    def recover_stale_jobs(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self.config.worker_stale_seconds)).isoformat(
            timespec="seconds"
        )
        rows = self.db.query(
            "SELECT job_id FROM jobs WHERE status='running' AND last_started_at IS NOT NULL AND last_started_at < ?",
            (cutoff,),
        )
        for row in rows:
            self.logger.warning("recovering stale job %s (worker likely died)", row["job_id"])
            self.jobs.reset_stale_running(row["job_id"])
        return len(rows)

    def _claim_any_queued(self) -> dict | None:
        candidates = self.jobs.list(status=JobStatus.QUEUED)
        for job in candidates:
            if self.jobs.claim_queued(job["job_id"]):
                return self.jobs.get(job["job_id"])
        return None

    def run_one_job(self) -> bool:
        """Claim and run a single job. Returns True if a job was processed."""
        job = self._claim_any_queued()
        if not job:
            return False

        self._heartbeat("busy", job["job_id"])
        self.logger.info("running job %s (%s) phase=%s", job["job_id"], job["job_name"], job["phase"])

        outcome, _status = run_job_and_record(
            self.ctx, self.jobs, job, self.config.worker_poll_interval_seconds, self.logger,
        )

        if outcome is not None:
            self.logger.info(
                "job %s finished: fetched=%d inserted=%d updated=%d review=%d errors=%d",
                job["job_id"], outcome.fetched, outcome.inserted, outcome.updated, outcome.reviewed, outcome.errors,
            )
        self._heartbeat("idle", None)
        return True

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        self.logger.info("worker %s starting", self.worker_id)
        last_recovery = 0.0
        while not self._stop:
            try:
                if time.monotonic() - last_recovery > self.config.worker_stale_seconds / 2:
                    self.recover_stale_jobs()
                    last_recovery = time.monotonic()
                did_work = self.run_one_job()
            except Exception:
                self.logger.exception("worker loop error")
                did_work = False
            if not did_work:
                self._sleep(self.config.worker_poll_interval_seconds)
        self.db.execute("UPDATE workers SET status='stopped', last_heartbeat=? WHERE worker_id=?", (now_iso(), self.worker_id))
        self.logger.info("worker %s stopped", self.worker_id)

    def _sleep(self, seconds: float) -> None:
        for _ in range(int(seconds * 10)):
            if self._stop:
                return
            time.sleep(0.1)
