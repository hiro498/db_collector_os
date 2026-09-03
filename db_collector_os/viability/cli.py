"""`db-collector viability ...` -- CLI surface for the DB viability
assessment tool. Reuses the same Database/AppConfig plumbing as the rest of
db-collector (see cli.py); no separate app, no separate DB file.
"""

from __future__ import annotations

import json
import sys

import click
import yaml

from ..config import AppConfig
from ..database import Database
from .config import default_config_path, load_viability_config
from .keyword_sources.csv_import import CsvKeywordSource
from .report import build_report, render_text
from .runner import EvaluationRunner, Phase1NotPassedError
from .serp_sources.csv_import import CsvSerpSource
from .store import ViabilityStore


def _db(ctx: click.Context) -> Database:
    return Database(ctx.obj["config"].db_path)


def _runner(ctx: click.Context) -> EvaluationRunner:
    config: AppConfig = ctx.obj["config"]
    vconfig = load_viability_config(default_config_path(config.config_path))
    return EvaluationRunner(_db(ctx), vconfig)


@click.group()
def viability() -> None:
    """DB候補テーマの需要・競合判定ツール (Phase 1: demand, Phase 2: competition)."""


# --------------------------------------------------------------------------
# idea
# --------------------------------------------------------------------------

@viability.group("idea")
def idea_group() -> None:
    """Manage DB candidate ideas (themes)."""


@idea_group.command("create")
@click.option("--theme", required=True, help="テーマ名 (例: アクセサリーのオーダーメイド工房)")
@click.option("--category", default=None)
@click.option("--notes", default=None)
@click.pass_context
def idea_create(ctx: click.Context, theme: str, category: str | None, notes: str | None) -> None:
    runner = _runner(ctx)
    idea_id = runner.create_idea(theme, category, notes)
    click.echo(idea_id)


@idea_group.command("list")
@click.option("--status", default=None)
@click.pass_context
def idea_list(ctx: click.Context, status: str | None) -> None:
    store = ViabilityStore(_db(ctx))
    for row in store.list_ideas(status=status):
        click.echo(f"{row['idea_id']:40} status={row['status']:10} theme={row['theme_name']}")


@idea_group.command("show")
@click.argument("idea_id")
@click.pass_context
def idea_show(ctx: click.Context, idea_id: str) -> None:
    store = ViabilityStore(_db(ctx))
    idea = store.get_idea(idea_id)
    if not idea:
        click.echo("not found", err=True)
        sys.exit(1)
    click.echo(json.dumps(idea, indent=2, ensure_ascii=False, default=str))


# --------------------------------------------------------------------------
# keywords
# --------------------------------------------------------------------------

@viability.group("keywords")
def keywords_group() -> None:
    """Build the keyword candidate set for an idea."""


@keywords_group.command("generate")
@click.argument("idea_id")
@click.option("--spec", "spec_path", required=True, type=click.Path(exists=True), help=(
    "YAML: {main_keywords: [...], axes: {category: [...], region: [...], ...}, "
    "combos: [[...], ...]}"
))
@click.pass_context
def keywords_generate(ctx: click.Context, idea_id: str, spec_path: str) -> None:
    with open(spec_path, encoding="utf-8") as fh:
        spec = yaml.safe_load(fh) or {}
    runner = _runner(ctx)
    candidate_ids = runner.add_keywords_from_generator(
        idea_id, spec.get("main_keywords", []), spec.get("axes", {}), spec.get("combos", [])
    )
    click.echo(f"{len(candidate_ids)} keyword candidate(s) added/verified")


@keywords_group.command("import-csv")
@click.argument("idea_id")
@click.argument("csv_path", type=click.Path(exists=True))
@click.pass_context
def keywords_import_csv(ctx: click.Context, idea_id: str, csv_path: str) -> None:
    runner = _runner(ctx)
    candidate_ids = runner.add_keywords_from_csv(idea_id, csv_path)
    click.echo(f"{len(candidate_ids)} keyword candidate(s) added/verified")


@keywords_group.command("list")
@click.argument("idea_id")
@click.pass_context
def keywords_list(ctx: click.Context, idea_id: str) -> None:
    store = ViabilityStore(_db(ctx))
    for row in store.list_keyword_candidates(idea_id):
        marker = "*" if row["is_main"] else " "
        click.echo(f"{marker} {row['keyword']:40} axis={row['axis_json']}")


# --------------------------------------------------------------------------
# metrics (Phase 1 data)
# --------------------------------------------------------------------------

@viability.group("metrics")
def metrics_group() -> None:
    """Import monthly search volume for an idea's keyword candidates."""


@metrics_group.command("import-csv")
@click.argument("idea_id")
@click.argument("csv_path", type=click.Path(exists=True))
@click.option("--source-label", default="csv_import", help="recorded in keyword_metrics.source")
@click.pass_context
def metrics_import_csv(ctx: click.Context, idea_id: str, csv_path: str, source_label: str) -> None:
    runner = _runner(ctx)
    count = runner.import_keyword_metrics(idea_id, CsvKeywordSource(csv_path), source_label=source_label)
    click.echo(f"{count} keyword metric row(s) imported")


# --------------------------------------------------------------------------
# phase1 / phase2 / serp / evaluate
# --------------------------------------------------------------------------

@viability.command("phase1-run")
@click.argument("idea_id")
@click.pass_context
def phase1_run(ctx: click.Context, idea_id: str) -> None:
    runner = _runner(ctx)
    summary, run_id = runner.run_phase1(idea_id)
    click.echo(json.dumps({"run_id": run_id, **summary}, indent=2, ensure_ascii=False))
    if summary["phase1_result"] != "PASS":
        click.echo("Phase 1 FAIL -> NO-GO (Phase 2 skipped)", err=True)


@viability.group("serp")
def serp_group() -> None:
    """Import SERP results for Phase 2."""


@serp_group.command("import-csv")
@click.argument("run_id")
@click.argument("idea_id")
@click.argument("csv_path", type=click.Path(exists=True))
@click.option("--source-label", default="csv_import")
@click.pass_context
def serp_import_csv(ctx: click.Context, run_id: str, idea_id: str, csv_path: str, source_label: str) -> None:
    runner = _runner(ctx)
    try:
        count = runner.import_serp_results(run_id, idea_id, CsvSerpSource(csv_path, default_source=source_label))
    except Phase1NotPassedError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    click.echo(f"{count} keyword(s) worth of SERP results imported")


@viability.command("phase2-run")
@click.argument("run_id")
@click.pass_context
def phase2_run(ctx: click.Context, run_id: str) -> None:
    runner = _runner(ctx)
    summary = runner.run_phase2(run_id)
    click.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@viability.command("evaluate")
@click.argument("run_id")
@click.pass_context
def evaluate(ctx: click.Context, run_id: str) -> None:
    runner = _runner(ctx)
    evaluation = runner.finalize_evaluation(run_id)
    click.echo(json.dumps(evaluation, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------
# report / runs
# --------------------------------------------------------------------------

@viability.command("report")
@click.argument("idea_id")
@click.option("--run-id", default=None, help="defaults to the idea's latest run")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.pass_context
def report_cmd(ctx: click.Context, idea_id: str, run_id: str | None, output_format: str) -> None:
    store = ViabilityStore(_db(ctx))
    report = build_report(store, idea_id, run_id)
    if output_format == "json":
        click.echo(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        click.echo(render_text(report))


@viability.command("runs-list")
@click.argument("idea_id")
@click.pass_context
def runs_list(ctx: click.Context, idea_id: str) -> None:
    store = ViabilityStore(_db(ctx))
    for row in store.list_runs(idea_id):
        click.echo(f"{row['run_id']:40} phase={row['phase']:16} status={row['status']:10} started={row['started_at']}")
