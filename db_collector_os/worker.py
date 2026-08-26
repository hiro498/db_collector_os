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

from .collectors import CollectorContext, get_collector
from .config import AppConfig
from .database import Database
from .job_registry import JobRegistry, now_iso, now_plus
from .logging_config import get_logger
from .models.enums import JobPhase, JobStatus, RunStatus


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

        try:
            collector = get_collector(job["collector_type"], self.ctx)
            outcome = collector.run_once(job)
        except Exception as exc:  # per-job isolation: one job's failure never kills the worker
            self.logger.exception("job %s failed: %s", job["job_id"], exc)
            checkpoint = self.ctx.checkpoints.load(job["job_id"])
            run_id = checkpoint["state"].get("current_run_id")
            if run_id:
                self.ctx.run_history.finish(run_id, RunStatus.FAILED, error_count=1)
            self.jobs.finish(job["job_id"], JobStatus.FAILED)
            self._heartbeat("idle", None)
            return True

        job_after = self.jobs.get(job["job_id"])
        checkpoint = self.ctx.checkpoints.load(job["job_id"])
        run_id = checkpoint["state"].get("current_run_id")
        still_working = job_after["phase"] != JobPhase.INCREMENTAL and not self.ctx.fetch_queue.is_empty(job["job_id"])

        run_status = RunStatus.COMPLETED
        if run_id:
            self.ctx.run_history.finish(run_id, run_status, **outcome.as_kwargs())
        state = checkpoint["state"]
        state.pop("current_run_id", None)
        self.ctx.checkpoints.save(job["job_id"], None, job_after["phase"], state)

        if still_working:
            self.jobs.finish(job["job_id"], JobStatus.RETRY, next_run_override=now_plus(self.config.worker_poll_interval_seconds))
        else:
            self.jobs.finish(job["job_id"], JobStatus.COMPLETED)

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
