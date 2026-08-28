"""Regression tests for the Phase 1 batch #1 production bug: a new
worker/CLI execution must always get its own run_history row.
run_history is immutable execution history -- a row that was already
finalized (completed or failed) must never be reused, re-finalized, or
have its started_at/finished_at/counts overwritten by a later execution,
even if checkpoint state carries a dangling current_run_id pointing at it
(the exact corruption observed in production: a run_id from 2026-08-27's
single-product proof got silently reused and re-finalized by a Phase 1
batch #1 retry the next day, with finished_at overwritten and all counts
zeroed out).
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from db_collector_os.cli import main
from db_collector_os.collectors import CollectorContext
from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType, RunStatus
from db_collector_os.worker import Worker


def make_job(jr: JobRegistry, **overrides) -> str:
    defaults = dict(
        job_name="Test Job", category="product", target_db="products", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="sample_official_site",
        rate_limit=0.0,  # tests drive multiple run_one_job() calls back-to-back within milliseconds
        config={"seed_urls": ["https://shop.example.com/product/1"]},
    )
    defaults.update(overrides)
    return jr.create(**defaults)


def _mock_one_page(responses_mod, url="https://shop.example.com/product/1"):
    responses_mod.add(responses_mod.GET, "https://shop.example.com/robots.txt", status=404)
    responses_mod.add(
        responses_mod.GET, url, status=200, content_type="text/html",
        body='<html><head><title>P</title><script type="application/ld+json">'
             '{"@type":"Product","name":"Widget"}</script></head><body><h1>Widget</h1></body></html>',
    )


def _run_once_via_worker(app_config, db, job_id: str, worker_id: str) -> None:
    JobRegistry(db).mark_queued(job_id)
    Worker(app_config, worker_id=worker_id, db=db).run_one_job()


def _inject_stale_current_run_id(app_config, db, job_id: str, run_id: str) -> None:
    """Simulate the exact production corruption: checkpoint.state still
    carries current_run_id pointing at an already-finalized run (e.g. a
    row from before this crash-resume mechanism existed, or any other
    edge case that leaves the key set after finalize)."""
    ctx = CollectorContext.build(app_config, db)
    checkpoint = ctx.checkpoints.load(job_id)
    checkpoint["state"]["current_run_id"] = run_id
    ctx.checkpoints.save(job_id, None, checkpoint["phase"], checkpoint["state"])


import responses as responses_lib  # noqa: E402  (grouped near use for readability)


@responses_lib.activate
def test_new_execution_gets_new_run_id_despite_stale_checkpoint_run_id(app_config, db):
    _mock_one_page(responses_lib)
    jr = JobRegistry(db)
    job_id = make_job(jr)

    _run_once_via_worker(app_config, db, job_id, "w1")
    old_run = db.query_one(
        "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1", (job_id,)
    )
    assert old_run["status"] == RunStatus.COMPLETED
    old_run_id = old_run["run_id"]

    _inject_stale_current_run_id(app_config, db, job_id, old_run_id)

    _run_once_via_worker(app_config, db, job_id, "w2")

    runs = db.query("SELECT * FROM run_history WHERE job_id=? ORDER BY started_at ASC, rowid ASC", (job_id,))
    assert len(runs) == 2, "second execution must create its own run_history row, not reuse the old one"
    new_run = runs[-1]
    assert new_run["run_id"] != old_run_id

    # Old row is completely untouched: run_history is immutable execution history.
    refreshed_old = db.query_one("SELECT * FROM run_history WHERE run_id=?", (old_run_id,))
    assert refreshed_old["started_at"] == old_run["started_at"]
    assert refreshed_old["finished_at"] == old_run["finished_at"]
    assert refreshed_old["status"] == old_run["status"]
    assert refreshed_old["fetched_count"] == old_run["fetched_count"]
    assert refreshed_old["inserted_count"] == old_run["inserted_count"]


@responses_lib.activate
def test_new_execution_after_stale_failed_run_gets_new_run_id_and_old_row_unchanged(app_config, db, monkeypatch):
    jr = JobRegistry(db)
    job_id = make_job(jr)

    import db_collector_os.collectors.pipeline as pipeline_module

    def boom(*_args, **_kwargs):
        raise RuntimeError("adapter exploded")

    monkeypatch.setattr(pipeline_module.BaseCollector, "run_once", boom)
    _run_once_via_worker(app_config, db, job_id, "w1")
    monkeypatch.undo()

    old_run = db.query_one(
        "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1", (job_id,)
    )
    assert old_run["status"] == RunStatus.FAILED
    old_run_id = old_run["run_id"]

    _inject_stale_current_run_id(app_config, db, job_id, old_run_id)

    _mock_one_page(responses_lib)
    jr.resume(job_id)  # a failed job needs an explicit resume before it's re-queueable
    _run_once_via_worker(app_config, db, job_id, "w2")

    runs = db.query("SELECT * FROM run_history WHERE job_id=? ORDER BY started_at ASC, rowid ASC", (job_id,))
    assert len(runs) == 2
    new_run = runs[-1]
    assert new_run["run_id"] != old_run_id
    assert new_run["status"] == RunStatus.COMPLETED

    refreshed_old = db.query_one("SELECT * FROM run_history WHERE run_id=?", (old_run_id,))
    assert refreshed_old["status"] == RunStatus.FAILED, "old failed row must stay failed, never re-finalized to completed"
    assert refreshed_old["finished_at"] == old_run["finished_at"]
    assert refreshed_old["started_at"] == old_run["started_at"]


def _write_config(tmp_path, monkeypatch):
    import yaml

    home = tmp_path / "var"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"home_dir": str(home), "db_path": "t.sqlite3"}), encoding="utf-8")
    return config_path


@responses_lib.activate
def test_cli_jobs_run_each_invocation_gets_unique_run_id(tmp_path, monkeypatch):
    responses_lib.add(responses_lib.GET, "https://example.com/robots.txt", status=404)
    responses_lib.add(
        responses_lib.GET, "https://example.com/p", status=200, content_type="text/html",
        body='<html><head><title>P</title><script type="application/ld+json">'
             '{"@type":"Product","name":"Widget"}</script></head><body><h1>Widget</h1></body></html>',
    )

    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    runner.invoke(main, ["--config", str(config_path), "migrate"])

    from db_collector_os.config import load_config
    from db_collector_os.database import Database

    cfg = load_config(str(config_path))
    db = Database(cfg.db_path)
    job_id = JobRegistry(db).create(
        job_name="t", category="product", target_db="d", target_table="entities",
        collector_type="official_site", adapter="sample_official_site",
        config={"seed_urls": ["https://example.com/p"]}, max_pages=5, rate_limit=0.0,
    )
    db.close()

    run_ids = []
    for _ in range(3):
        result = runner.invoke(main, ["--config", str(config_path), "jobs", "run", job_id])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] in ("completed", "retry")

        db = Database(cfg.db_path)
        latest = db.query_one(
            "SELECT run_id FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1", (job_id,)
        )
        run_ids.append(latest["run_id"])
        db.close()
        # jobs run requires status in (idle, queued, retry) internally via
        # run_once's own queue draining; re-queue between invocations exactly
        # like a real scheduler tick would.
        db = Database(cfg.db_path)
        JobRegistry(db).mark_queued(job_id)
        db.close()

    assert len(set(run_ids)) == len(run_ids), f"expected unique run_ids per invocation, got {run_ids}"


@responses_lib.activate
def test_run_history_counts_are_execution_local_not_cumulative(app_config, db):
    jr = JobRegistry(db)
    job_id = make_job(jr, config={
        "seed_urls": ["https://shop.example.com/product/1"],
        "discovery": {"internal_links": False, "related_entities": False},
    })

    responses_lib.add(responses_lib.GET, "https://shop.example.com/robots.txt", status=404)
    responses_lib.add(
        responses_lib.GET, "https://shop.example.com/product/1", status=200, content_type="text/html",
        body='<html><head><title>P</title><script type="application/ld+json">'
             '{"@type":"Product","name":"Widget"}</script></head><body><h1>Widget</h1></body></html>',
    )
    _run_once_via_worker(app_config, db, job_id, "w1")
    first_run = db.query_one(
        "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1", (job_id,)
    )
    assert first_run["fetched_count"] == 1
    assert first_run["inserted_count"] == 1

    # Second execution: config now also seeds a second, brand-new URL. Only
    # THIS run's fetch should be reflected in the new row's counts -- not the
    # first run's counts added on top.
    responses_lib.add(
        responses_lib.GET, "https://shop.example.com/product/2", status=200, content_type="text/html",
        body='<html><head><title>P2</title><script type="application/ld+json">'
             '{"@type":"Product","name":"Widget 2"}</script></head><body><h1>Widget 2</h1></body></html>',
    )
    db.execute(
        "UPDATE jobs SET config_json=? WHERE job_id=?",
        (json.dumps({
            "seed_urls": ["https://shop.example.com/product/1", "https://shop.example.com/product/2"],
            "discovery": {"internal_links": False, "related_entities": False},
        }), job_id),
    )
    _run_once_via_worker(app_config, db, job_id, "w2")

    runs = db.query("SELECT * FROM run_history WHERE job_id=? ORDER BY started_at ASC, rowid ASC", (job_id,))
    assert len(runs) == 2
    second_run = runs[-1]
    # Execution-local: this run only fetched the one new URL (product/1 was
    # already 'done' and is not re-fetched), not "1 (this run) + 1 (last run)".
    assert second_run["fetched_count"] == 1
    assert second_run["inserted_count"] == 1
    # And the first run's row is untouched.
    assert runs[0]["fetched_count"] == first_run["fetched_count"]
    assert runs[0]["inserted_count"] == first_run["inserted_count"]
