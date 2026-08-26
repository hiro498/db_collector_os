"""Scheduler: reads the Job Registry, and moves due, enabled jobs into the
`queued` state for Workers to pick up -- gated by the Resource Controller so
a busy VPS is never handed more concurrent work than it can safely run.

Runs as `db-collector-scheduler.service` under systemd; also usable as a
library (`Scheduler.tick()`) for tests and the CLI's `run-once` mode.
"""

from __future__ import annotations

import signal
import time

from .config import AppConfig
from .database import Database
from .job_registry import JobRegistry
from .logging_config import get_logger
from .resource_controller import ResourceController


class Scheduler:
    def __init__(self, config: AppConfig, db: Database | None = None):
        self.config = config
        self.db = db or Database(config.db_path)
        self.jobs = JobRegistry(self.db)
        self.resources = ResourceController(config.resource_thresholds)
        self.logger = get_logger("scheduler", config.log_dir, config.log_level)
        self._stop = False

    def request_stop(self, *_args) -> None:
        self._stop = True

    def tick(self) -> int:
        """Admit as many due jobs as current resource headroom allows.
        Returns the number of jobs queued this tick.
        """
        due = self.jobs.due_jobs()
        if not due:
            return 0

        admitted = 0
        for job in due:
            ok, reason = self.resources.can_admit_new_job()
            if not ok:
                self.logger.info(
                    "resource controller suppressing new job admission (%s); %d job(s) still waiting",
                    reason, len(due) - admitted,
                )
                break
            self.jobs.mark_queued(job["job_id"])
            self.logger.info("queued job %s (%s) priority=%s", job["job_id"], job["job_name"], job["priority"])
            admitted += 1
        return admitted

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        self.logger.info("scheduler starting, interval=%.1fs", self.config.scheduler_interval_seconds)
        while not self._stop:
            try:
                self.tick()
            except Exception:
                self.logger.exception("scheduler tick failed")
            for _ in range(int(self.config.scheduler_interval_seconds * 10)):
                if self._stop:
                    break
                time.sleep(0.1)
        self.logger.info("scheduler stopped")
