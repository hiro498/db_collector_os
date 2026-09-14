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


@ci.command("ai-analyze")
@click.argument("page_id")
@click.pass_context
def ai_analyze(ctx: click.Context, page_id: str) -> None:
    """PHASE 12: run AI Search Analysis for one already-crawled page."""
    result = service.analyze_ai_page(ctx.obj["config"], page_id)
    click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))


@ci.command("ai-recompute")
@click.argument("page_id")
@click.pass_context
def ai_recompute(ctx: click.Context, page_id: str) -> None:
    """Re-run AI Search Analysis from stored page elements (no re-crawl)."""
    result = service.recompute_ai_analysis(ctx.obj["config"], page_id)
    click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))


@ci.command("ai-status")
@click.argument("page_id")
@click.pass_context
def ai_status(ctx: click.Context, page_id: str) -> None:
    result = service.get_ai_analysis(ctx.obj["config"], page_id)
    if result is None:
        click.echo(f"no AI Search Analysis for page: {page_id}", err=True)
        sys.exit(1)
    click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))


@ci.group("observation")
def observation() -> None:
    """PHASE 13: external SERP/AIO/AI-Mode/fan-out observation storage and
    Readiness-vs-Reality rollup (never mixed with PHASE 12's internal
    readiness score -- see ai_search/observation/__init__.py)."""


@observation.command("status")
@click.pass_context
def observation_status(ctx: click.Context) -> None:
    result = service.observation_status(ctx.obj["config"])
    click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))


@observation.command("import")
@click.argument("file_path")
@click.option("--type", "observation_type", required=True,
              type=click.Choice(["organic", "aio", "ai_mode", "fanout", "gsc"]),
              help="Which observation table this file's records belong to.")
@click.option("--provider", default=None, help="Free-text label for where this data came from.")
@click.pass_context
def observation_import(ctx: click.Context, file_path: str, observation_type: str, provider: str | None) -> None:
    """Offline-import a JSON/CSV file of externally-gathered observations
    (the primary way real data enters PHASE 13 -- live fetch from this
    environment is a known, confirmed block, see `ci observe`)."""
    result = service.import_observation(ctx.obj["config"], file_path, observation_type, provider=provider)
    click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))


@observation.command("list")
@click.option("--limit", default=50, type=int)
@click.pass_context
def observation_list(ctx: click.Context, limit: int) -> None:
    """List recent import batches."""
    for batch in service.list_observation_import_batches(ctx.obj["config"], limit=limit):
        click.echo(
            f"{batch['import_batch_id']:24} type={batch['observation_type']:8} "
            f"provider={batch['provider'] or '-':16} imported={batch['imported_count']} "
            f"skipped={batch['skipped_duplicate_count']} errors={batch['error_count']} "
            f"at={batch['imported_at']}"
        )


@observation.command("show")
@click.argument("page_id")
@click.option("--recompute", is_flag=True, help="Recompute from currently stored observations before showing.")
@click.pass_context
def observation_show(ctx: click.Context, page_id: str, recompute: bool) -> None:
    """Show the stored Readiness-vs-Reality rollup for one page. Every
    field not yet observed prints as `null` -- never 0 or a guessed value."""
    config: AppConfig = ctx.obj["config"]
    result = service.recompute_page_visibility(config, page_id) if recompute else service.get_page_visibility(config, page_id)
    if result is None:
        click.echo(f"no visibility computed yet for page {page_id} -- run with --recompute first", err=True)
        sys.exit(1)
    click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))


@ci.group("observe")
def observe() -> None:
    """Run a live observation provider for one query (spec section 4).
    Default providers make no network call in this environment -- known,
    confirmed blocked -- and report `unavailable`, never a fabricated
    result. See `ci observation import` for the real data path."""


def _observe_common(ctx: click.Context, surface: str, query: str, country: str | None, language: str | None,
                     device: str | None) -> None:
    result = service.observe(ctx.obj["config"], surface, query, country=country, language=language, device=device)
    click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))


@observe.command("organic")
@click.argument("query")
@click.option("--country", default=None)
@click.option("--language", default=None)
@click.option("--device", default=None)
@click.pass_context
def observe_organic(ctx: click.Context, query: str, country: str | None, language: str | None,
                     device: str | None) -> None:
    _observe_common(ctx, "organic", query, country, language, device)


@observe.command("aio")
@click.argument("query")
@click.option("--country", default=None)
@click.option("--language", default=None)
@click.option("--device", default=None)
@click.pass_context
def observe_aio(ctx: click.Context, query: str, country: str | None, language: str | None,
                device: str | None) -> None:
    _observe_common(ctx, "aio", query, country, language, device)


@observe.command("ai-mode")
@click.argument("query")
@click.option("--country", default=None)
@click.option("--language", default=None)
@click.option("--device", default=None)
@click.pass_context
def observe_ai_mode(ctx: click.Context, query: str, country: str | None, language: str | None,
                     device: str | None) -> None:
    _observe_common(ctx, "ai-mode", query, country, language, device)


@observe.command("fanout")
@click.argument("query")
@click.option("--country", default=None)
@click.option("--language", default=None)
@click.option("--device", default=None)
@click.pass_context
def observe_fanout(ctx: click.Context, query: str, country: str | None, language: str | None,
                    device: str | None) -> None:
    _observe_common(ctx, "fanout", query, country, language, device)


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
