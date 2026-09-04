"""Admin UI: a lightweight FastAPI + Jinja2 dashboard. Read-mostly (the only
mutation routes are review resolve/dismiss and job pause/resume) so it is
safe to leave running unattended alongside the scheduler/worker.

Binds to 127.0.0.1 by default -- see README "Admin UI" section for how to
expose it safely (SSH tunnel or an authenticating reverse proxy). Never bind
0.0.0.0 without authentication in front of it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from ..candidates import CandidateStore
from ..config import AppConfig
from ..database import Database
from ..fetching import FetchQueue
from ..job_registry import JobRegistry
from ..metrics import MetricsStore
from ..resource_controller import ResourceController
from ..review import ReviewQueue
from ..run_history import RunHistoryStore

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

logger = logging.getLogger(__name__)


def _safe_lovehotel_summary(d: Database) -> dict[str, Any] | None:
    """Best-effort only: `lovehotel_audit` is expected to evolve on its own
    (Phase 1B classification work), so an API this dashboard doesn't yet
    know about (missing symbol, changed return shape) must never take the
    rest of the Admin Dashboard down with it -- it just means the 全国ラブ
    ホテルDB section is skipped for this request. Returns None either when
    the job isn't present in this DB or when the summary can't be produced.
    """
    try:
        from ..lovehotel_audit import LOVEHOTEL_JOB_ID, lovehotel_summary

        summary = lovehotel_summary(d, LOVEHOTEL_JOB_ID)
        if not summary.get("db_present"):
            return None
        # Touch every key dashboard.html actually renders now, so a shape
        # mismatch is caught here (section silently omitted) instead of
        # surfacing as a Jinja error on every dashboard load.
        c = summary["classification"]
        _ = (c["total"], c["counts"]["facility"], c["counts"]["listing"], c["counts"]["homepage"],
             c["counts"]["closed"], c["counts"]["incomplete"], c["counts"]["unknown"])
        cov = summary["coverage"]
        _ = (cov["prefecture_covered_count"], cov["prefecture_total"], cov["prefecture_info_rate"], cov["city_info_rate"])
        col = summary["collection"]
        _ = (col["total_candidates"], col["new_candidates"], col["fetch_done"], col["fetch_queued"],
             col["fetch_failed"], col["duplicate_candidates"], col["review_candidates"])
        rev = summary["review"]
        _ = (rev["total_open"], rev["order"], rev["labels"], rev["buckets"])
        comp = summary["completion"]
        _ = (comp["complete"], comp["order"], comp["labels"], comp["gates"])
        return summary
    except Exception:
        logger.exception("lovehotel dashboard summary unavailable; omitting section")
        return None


def create_app(config: AppConfig) -> FastAPI:
    app = FastAPI(title="DB Collector OS Admin")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def db() -> Database:
        return Database(config.db_path)

    @app.get("/")
    def dashboard(request: Request):
        d = db()
        jobs = JobRegistry(d)
        review = ReviewQueue(d)
        metrics = MetricsStore(d)
        resources = ResourceController(config.resource_thresholds)
        today = metrics.today()
        snap = resources.snapshot()

        all_jobs = jobs.list()
        lovehotel = _safe_lovehotel_summary(d)
        ctx = {
            "db_count": len({j["target_db"] for j in all_jobs}),
            "active_jobs": sum(1 for j in all_jobs if j["enabled"]),
            "queued_jobs": sum(1 for j in all_jobs if j["status"] == "queued"),
            "running_jobs": sum(1 for j in all_jobs if j["status"] == "running"),
            "completed_jobs": sum(1 for j in all_jobs if j["status"] == "completed"),
            "failed_jobs": sum(1 for j in all_jobs if j["status"] == "failed"),
            "review_count": review.count_open(),
            "today": today,
            "resources": snap.as_dict(),
            "thresholds": config.resource_thresholds,
            "lovehotel": lovehotel,
        }
        return templates.TemplateResponse(request, "dashboard.html", ctx)

    @app.get("/dbs")
    def db_list(request: Request):
        d = db()
        jobs = JobRegistry(d)
        entities_counts = {
            r["job_id"]: r["n"]
            for r in d.query("SELECT job_id, COUNT(*) AS n FROM entities WHERE deleted_at IS NULL GROUP BY job_id")
        }
        today_new = {
            r["job_id"]: r["n"]
            for r in d.query(
                "SELECT job_id, COUNT(*) AS n FROM entities WHERE date(created_at) = date('now') GROUP BY job_id"
            )
        }
        today_updated = {
            r["job_id"]: r["n"]
            for r in d.query(
                "SELECT job_id, COUNT(*) AS n FROM entities WHERE date(updated_at) = date('now') "
                "AND date(created_at) != date('now') GROUP BY job_id"
            )
        }
        rows = []
        for job in jobs.list():
            rows.append(
                {
                    "job": job,
                    "count": entities_counts.get(job["job_id"], 0),
                    "new_today": today_new.get(job["job_id"], 0),
                    "updated_today": today_updated.get(job["job_id"], 0),
                }
            )
        return templates.TemplateResponse(request, "dbs.html", {"rows": rows})

    @app.get("/jobs/{job_id}")
    def job_detail(request: Request, job_id: str):
        d = db()
        job = JobRegistry(d).get(job_id)
        fq = FetchQueue(d)
        candidates = CandidateStore(d)
        run_history = RunHistoryStore(d)
        review = ReviewQueue(d)
        ctx = {
            "job": job,
            "queue_stats": fq.stats(job_id),
            "candidate_stats": candidates.counts_by_status(job_id),
            "runs": run_history.for_job(job_id, limit=20),
            "review_items": review.list_open(job_id),
            "entity_count": d.query_one(
                "SELECT COUNT(*) AS n FROM entities WHERE job_id=? AND deleted_at IS NULL", (job_id,)
            )["n"],
        }
        return templates.TemplateResponse(request, "job_detail.html", ctx)

    @app.post("/jobs/{job_id}/pause")
    def job_pause(job_id: str):
        JobRegistry(db()).pause(job_id)
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/{job_id}/resume")
    def job_resume(job_id: str):
        JobRegistry(db()).resume(job_id)
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @app.get("/review")
    def review_page(request: Request):
        d = db()
        review = ReviewQueue(d)
        return templates.TemplateResponse(request, "review.html", {"items": review.list_open(limit=500)})

    @app.post("/review/{review_id}/resolve")
    def review_resolve(review_id: int):
        ReviewQueue(db()).resolve(review_id)
        return RedirectResponse(url="/review", status_code=303)

    @app.post("/review/{review_id}/dismiss")
    def review_dismiss(review_id: int):
        ReviewQueue(db()).dismiss(review_id)
        return RedirectResponse(url="/review", status_code=303)

    @app.get("/healthz")
    def healthz():
        ok, detail = db().integrity_check()
        return {"ok": ok, "detail": detail}

    return app
