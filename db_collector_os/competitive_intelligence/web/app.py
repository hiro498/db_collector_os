"""Competitive Keyword / Content Discovery Engine -- P0 Web Dashboard (spec
sections 34-42). A separate FastAPI app from db_collector_os.admin (its own
routes/templates/port) -- this module never imports or mutates anything
under db_collector_os/admin/, so the existing Admin UI is entirely
unaffected by this package's presence.

Read-mostly, like the existing Admin UI: the only mutation routes are
starting/resuming/stopping/reanalyzing/recomputing an investigation.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ...config import AppConfig
from .. import service
from ..enums import InputMode

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
PAGE_SIZE = 50


def create_ci_app(config: AppConfig) -> FastAPI:
    app = FastAPI(title="Competitive Keyword / Content Discovery Engine")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/")
    def top(request: Request):
        runs = service.list_investigations(config, limit=200)
        return templates.TemplateResponse(request, "top.html", {"runs": runs})

    @app.get("/new")
    def new_form(request: Request):
        return templates.TemplateResponse(request, "new.html", {"modes": InputMode.ALL})

    @app.post("/new")
    def new_submit(
        url: str = Form(...), mode: str = Form(InputMode.AUTO), vertical: str = Form("general"),
    ):
        run_id = service.start_investigation(config, url, requested_mode=mode, vertical=vertical)
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    @app.get("/runs/{run_id}")
    def run_status(request: Request, run_id: str):
        result = service.get_status(config, run_id)
        if result is None:
            return templates.TemplateResponse(request, "not_found.html", {"run_id": run_id}, status_code=404)
        return templates.TemplateResponse(request, "run_status.html", {"run_id": run_id, **result})

    @app.post("/runs/{run_id}/resume")
    def run_resume(run_id: str):
        service.resume(config, run_id)
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    @app.post("/runs/{run_id}/stop")
    def run_stop(run_id: str):
        service.request_stop(config, run_id)
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    @app.post("/runs/{run_id}/reanalyze")
    def run_reanalyze(run_id: str):
        service.reanalyze(config, run_id)
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    @app.post("/runs/{run_id}/recompute-keywords")
    def run_recompute_keywords(run_id: str):
        service.recompute_keywords(config, run_id)
        return RedirectResponse(url=f"/runs/{run_id}/keywords", status_code=303)

    @app.get("/runs/{run_id}/audit")
    def run_audit(request: Request, run_id: str, offset: int = 0, status: str | None = None):
        result = service.get_status(config, run_id)
        if result is None:
            return templates.TemplateResponse(request, "not_found.html", {"run_id": run_id}, status_code=404)
        crawl_urls = service.list_crawl_urls(config, run_id, limit=PAGE_SIZE, offset=offset, status=status)
        return templates.TemplateResponse(request, "audit.html", {
            "run_id": run_id, "run": result["run"], "status_counts": result["crawl_url_status_counts"],
            "crawl_urls": crawl_urls, "offset": offset, "page_size": PAGE_SIZE, "status_filter": status,
        })

    @app.get("/runs/{run_id}/pages")
    def run_pages(
        request: Request, run_id: str, offset: int = 0, page_type: str | None = None,
        analysis_target: str | None = None, q: str | None = None, indexable: str | None = None,
        monetization_type: str | None = None, min_score: int | None = None,
    ):
        at_filter = None if analysis_target in (None, "") else analysis_target == "1"
        idx_filter = None if indexable in (None, "") else indexable == "1"
        pages = service.list_pages(
            config, run_id, limit=PAGE_SIZE, offset=offset, page_type=page_type or None,
            analysis_target=at_filter, q=q or None, indexable=idx_filter,
            monetization_type=monetization_type or None, min_score=min_score,
        )
        return templates.TemplateResponse(request, "pages.html", {
            "run_id": run_id, "pages": pages, "offset": offset, "page_size": PAGE_SIZE,
            "page_type": page_type, "analysis_target": analysis_target, "q": q or "",
            "indexable": indexable, "monetization_type": monetization_type, "min_score": min_score,
        })

    @app.get("/runs/{run_id}/keywords")
    def run_keywords(
        request: Request, run_id: str, offset: int = 0, importance: str | None = None,
        intent_group: str | None = None, min_commercial_score: int | None = None,
        branded_type: str | None = None, is_local: str | None = None, keyword_class: str | None = None,
        q: str | None = None,
    ):
        local_filter = None if is_local in (None, "") else is_local == "1"
        keywords = service.list_keywords(
            config, run_id, limit=PAGE_SIZE, offset=offset, importance=importance or None,
            intent_group=intent_group or None, min_commercial_score=min_commercial_score,
            branded_type=branded_type or None, is_local=local_filter, keyword_class=keyword_class or None,
            q=q or None,
        )
        return templates.TemplateResponse(request, "keywords.html", {
            "run_id": run_id, "keywords": keywords, "offset": offset, "page_size": PAGE_SIZE,
            "importance": importance, "intent_group": intent_group, "min_commercial_score": min_commercial_score,
            "branded_type": branded_type, "is_local": is_local, "keyword_class": keyword_class, "q": q or "",
        })

    @app.get("/runs/{run_id}/keywords/{keyword_id}")
    def keyword_detail(request: Request, run_id: str, keyword_id: str):
        detail = service.get_keyword_detail(config, run_id, keyword_id)
        if detail is None:
            return templates.TemplateResponse(request, "not_found.html", {"run_id": run_id}, status_code=404)
        return templates.TemplateResponse(request, "keyword_detail.html", {"run_id": run_id, **detail})

    @app.get("/runs/{run_id}/export")
    def run_export(run_id: str, file: str = "keywords.csv"):
        allowed = {"domain_summary.csv", "pages.csv", "keywords.csv", "page_keywords.csv", "crawl_audit.csv"}
        if file not in allowed:
            return RedirectResponse(url=f"/runs/{run_id}")
        out_dir = Path(config.home_dir) / "ci_exports" / run_id
        service.export_csv(config, run_id, str(out_dir))
        return FileResponse(out_dir / file, filename=file, media_type="text/csv")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app
