"""CLI for the Competitive Keyword / Content Discovery Engine (spec section
44). Registered as a `ci` subcommand group onto the existing `db-collector`
CLI (see db_collector_os/cli.py) -- this module never touches any existing
command; `db-collector jobs/queue/review/scheduler/worker/admin` are
unaffected.

Deliberately mirrors db_collector_os/cli.py's structure (a `--config`-driven
AppConfig on ctx.obj, one function per subcommand, JSON output) so both
CLIs feel like the same tool.
"""

from __future__ import annotations

import json
import sys

import click

from ..config import AppConfig
from . import service
from .enums import InputMode


@click.group("ci")
def ci() -> None:
    """Competitive Keyword / Content Discovery Engine."""


@ci.command("analyze-lp")
@click.argument("url")
@click.option("--vertical", default="general")
@click.pass_context
def analyze_lp(ctx: click.Context, url: str, vertical: str) -> None:
    """Analyze a single advertiser LP URL (no domain-wide crawl)."""
    config: AppConfig = ctx.obj["config"]
    run_id = service.start_investigation(config, url, requested_mode=InputMode.ADVERTISER_LP, vertical=vertical)
    _echo_status(config, run_id)


@ci.command("analyze-domain")
@click.argument("url")
@click.option("--vertical", default="general")
@click.pass_context
def analyze_domain(ctx: click.Context, url: str, vertical: str) -> None:
    """Crawl an affiliate domain to convergence and analyze every page."""
    config: AppConfig = ctx.obj["config"]
    run_id = service.start_investigation(config, url, requested_mode=InputMode.AFFILIATE_DOMAIN, vertical=vertical)
    _echo_status(config, run_id)


@ci.command("status")
@click.argument("run_id")
@click.pass_context
def status(ctx: click.Context, run_id: str) -> None:
    _echo_status(ctx.obj["config"], run_id)


@ci.command("resume")
@click.argument("run_id")
@click.pass_context
def resume(ctx: click.Context, run_id: str) -> None:
    """Continue a stopped/interrupted run from its saved state (never
    re-fetches already-completed URLs)."""
    config: AppConfig = ctx.obj["config"]
    service.resume(config, run_id)
    _echo_status(config, run_id)


@ci.command("stop")
@click.argument("run_id")
@click.pass_context
def stop(ctx: click.Context, run_id: str) -> None:
    """Request a safe stop -- honored at the next URL boundary, not mid-fetch."""
    service.request_stop(ctx.obj["config"], run_id)
    click.echo(f"stop requested for {run_id}")


@ci.command("reanalyze")
@click.argument("run_id")
@click.pass_context
def reanalyze(ctx: click.Context, run_id: str) -> None:
    """Re-run classification + keyword scoring from stored HTML structure.
    Makes no network requests (see RECRAWL/REANALYZE separation, spec 45)."""
    config: AppConfig = ctx.obj["config"]
    service.reanalyze(config, run_id)
    _echo_status(config, run_id)


@ci.command("recompute-keywords")
@click.argument("run_id")
@click.pass_context
def recompute_keywords(ctx: click.Context, run_id: str) -> None:
    """Re-run only cross-page keyword score finalization (no re-parse)."""
    service.recompute_keywords(ctx.obj["config"], run_id)
    click.echo(f"keyword scores recomputed for {run_id}")


@ci.command("list")
@click.option("--limit", default=50, type=int)
@click.pass_context
def list_runs(ctx: click.Context, limit: int) -> None:
    runs = service.list_investigations(ctx.obj["config"], limit=limit)
    for run in runs:
        click.echo(
            f"{run['crawl_run_id']:24} {run['domain']:30} mode={run['input_mode']:16} "
            f"status={run['status']:10} converged={run['converged']} pages={run['analyzed_pages']}"
        )


@ci.command("export")
@click.argument("run_id")
@click.option("--out-dir", default="./var/ci_exports")
@click.pass_context
def export(ctx: click.Context, run_id: str, out_dir: str) -> None:
    paths = service.export_csv(ctx.obj["config"], run_id, out_dir)
    for path in paths:
        click.echo(path)


@ci.group("web")
def web() -> None:
    """Competitive Intelligence Web Dashboard process."""


@web.command("serve")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
@click.pass_context
def web_serve(ctx: click.Context, host: str | None, port: int | None) -> None:
    import uvicorn

    from .web.app import create_ci_app

    config: AppConfig = ctx.obj["config"]
    app = create_ci_app(config)
    uvicorn.run(app, host=host or config.admin_host, port=port or (config.admin_port + 1))


def _echo_status(config: AppConfig, run_id: str) -> None:
    result = service.get_status(config, run_id)
    if result is None:
        click.echo(f"no such run: {run_id}", err=True)
        sys.exit(1)
    click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
