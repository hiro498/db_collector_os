"""Regression tests for the generic "config seed guarantee": every URL in a
job's CURRENT config_json.seed_urls must reach fetch_queue, idempotently,
regardless of which process does the enqueueing and regardless of job
phase/checkpoint state -- not just Good-Smile-specific.

Context: Phase 1 batch #1's first real VPS retry reported
RUN_LIFECYCLE_GATE=PASS (the run-lifecycle fix worked) but
NEW_SEED_LIST_PRESENT_IN_QUEUE=NO / BATCH_FETCHED=0 -- the Scale Figure
list seed never reached fetch_queue even though config_json genuinely had
it. Root-cause investigation (see docs/first_production_db.md) found the
existing per-tick guarantee (BaseCollector.run_once() calling
_ensure_seed_urls_queued()) is correct in isolation, but entirely depends
on the long-running db-collector-worker@1.service process actually having
reloaded code that includes it -- the worker-reload gate added earlier
only restarts the worker when it judges it safe to (no active run
elsewhere), so a batch can proceed with a worker still serving older code
in exactly the scenario that matters most: right after a fix like this one
lands. Fixed generically by extracting the guarantee into a standalone
`ensure_seed_urls_queued()` function (db_collector_os/collectors/
pipeline.py) callable both from the pipeline (as before) AND directly,
synchronously, from a fresh CLI process (`db-collector jobs reseed`) --
guaranteed fresh code every time since it's not a long-running process.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import responses
import yaml

from db_collector_os.collectors import CollectorContext
from db_collector_os.collectors.pipeline import ensure_seed_urls_queued
from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType, JobPhase
from db_collector_os.worker import Worker

REPO_ROOT = Path(__file__).parent.parent
GOODSMILE_YAML = REPO_ROOT / "config/jobs/prod_figure_official_site.yaml"
LIST_URL = "https://www.goodsmile.com/en/scalefigure_list"
PRODUCT_URL = (
    "https://www.goodsmile.com/en/product/1141716/"
    "Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2Btoridamono"
)


def _sync_job_from_real_yaml(registry: JobRegistry, yaml_path: Path = GOODSMILE_YAML) -> str:
    """Mirrors `db-collector jobs sync` exactly (see cli.py::jobs_sync) --
    loads the REAL production job YAML rather than a hand-rolled test dict,
    per the investigation into whether test fixture shape differs from
    production job dict/config_json shape.
    """
    spec = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return registry.create(
        job_id=spec.get("job_id"), job_name=spec["job_name"], category=spec["category"],
        target_db=spec.get("target_db", spec["category"]), target_table=spec.get("target_table", "entities"),
        collector_type=spec["collector_type"], adapter=spec["adapter"],
        priority=spec.get("priority", 50), enabled=spec.get("enabled", True),
        schedule=spec.get("schedule", "@hourly"), max_pages=spec.get("max_pages", 200),
        max_depth=spec.get("max_depth", 3), concurrency=spec.get("concurrency", 2),
        rate_limit=spec.get("rate_limit", 1.0), config=spec.get("config", {}),
    )


def _seed_pre_existing_proof_state(ctx: CollectorContext, job_id: str, low_discovery_streak: int = 3) -> str:
    """Reproduces the exact reported production state: the single-product
    proof already fetched/done, an entity already created from it,
    checkpoint already seeded and sitting in the 'collect' phase with a
    nonzero low_discovery_streak (multiple prior low-yield runs)."""
    qid = ctx.fetch_queue.enqueue(job_id, PRODUCT_URL, priority=50)
    ctx.fetch_queue.mark_done(qid, 200, content_hash="proofhash", etag=None, last_modified=None)
    entity_id = ctx.entities.create(
        job_id=job_id, entity_type="figure", name="Rikka Takarada & Akane Shinjo feat. toridamono",
        normalized_name="rikka takarada akane shinjo feat toridamono", canonical_url=PRODUCT_URL,
        domain="www.goodsmile.com", address=None, telephone=None, external_id="1141716",
        fingerprint="proof-fp", data={},
    )
    ctx.checkpoints.save(job_id, None, JobPhase.COLLECT, {"seeded": True, "low_discovery_streak": low_discovery_streak})
    return entity_id


# -- Test A --------------------------------------------------------------


def test_config_expansion_after_proof_queues_new_seed_without_touching_done_one(app_config, db):
    registry = JobRegistry(db)
    job_id = _sync_job_from_real_yaml(registry)
    registry.set_phase(job_id, JobPhase.COLLECT)
    ctx = CollectorContext.build(app_config, db)
    _seed_pre_existing_proof_state(ctx, job_id)

    job = registry.get(job_id)
    assert set(job["config_json"]["seed_urls"]) == {LIST_URL, PRODUCT_URL}  # real YAML shape, both seeds present

    newly_queued = ensure_seed_urls_queued(ctx, job)
    assert newly_queued == [LIST_URL]

    product_rows = db.query("SELECT * FROM fetch_queue WHERE job_id=? AND url=?", (job_id, PRODUCT_URL))
    assert len(product_rows) == 1  # no duplicate row
    assert product_rows[0]["status"] == "done"  # not forced back to queued/refetched

    list_row = db.query_one("SELECT * FROM fetch_queue WHERE job_id=? AND url=?", (job_id, LIST_URL))
    assert list_row is not None
    assert list_row["status"] == "queued"  # newly added, ready to be fetched


# -- Test B --------------------------------------------------------------


def test_calling_seed_guarantee_twice_does_not_duplicate(app_config, db):
    registry = JobRegistry(db)
    job_id = _sync_job_from_real_yaml(registry)
    registry.set_phase(job_id, JobPhase.COLLECT)
    ctx = CollectorContext.build(app_config, db)
    _seed_pre_existing_proof_state(ctx, job_id)
    job = registry.get(job_id)

    first = ensure_seed_urls_queued(ctx, job)
    second = ensure_seed_urls_queued(ctx, job)
    assert first == [LIST_URL]
    assert second == []  # nothing new the second time

    rows = db.query("SELECT * FROM fetch_queue WHERE job_id=? AND url=?", (job_id, LIST_URL))
    assert len(rows) == 1


# -- Test C --------------------------------------------------------------


def test_third_seed_added_later_is_queued_on_next_call_only(app_config, db):
    registry = JobRegistry(db)
    job_id = _sync_job_from_real_yaml(registry)
    registry.set_phase(job_id, JobPhase.COLLECT)
    ctx = CollectorContext.build(app_config, db)
    _seed_pre_existing_proof_state(ctx, job_id)
    job = registry.get(job_id)
    ensure_seed_urls_queued(ctx, job)  # queues LIST_URL, matching current config

    third_url = "https://www.goodsmile.com/en/product/9999999/Another%2BFigure"
    cfg = dict(job["config_json"])
    cfg["seed_urls"] = [LIST_URL, PRODUCT_URL, third_url]
    db.execute("UPDATE jobs SET config_json=? WHERE job_id=?", (json.dumps(cfg), job_id))

    job2 = registry.get(job_id)
    newly_queued = ensure_seed_urls_queued(ctx, job2)
    assert newly_queued == [third_url]  # only the brand-new one, not LIST_URL/PRODUCT_URL again

    all_urls = {r["url"] for r in db.query("SELECT url FROM fetch_queue WHERE job_id=?", (job_id,))}
    assert all_urls == {PRODUCT_URL, LIST_URL, third_url}


# -- Test D --------------------------------------------------------------


@responses.activate
def test_run_lifecycle_fix_still_holds_alongside_seed_guarantee(app_config, db):
    """The run-lifecycle fix (fresh run_id per execution, old rows
    immutable) must keep working when combined with the seed guarantee --
    this was the other half of the same production batch's result and
    must not regress while fixing the seed bug.
    """
    responses.add(responses.GET, "https://www.goodsmile.com/robots.txt", status=404)
    responses.add(responses.GET, PRODUCT_URL, status=200, content_type="text/html",
                  body='<html><head><title>P</title><script type="application/ld+json">'
                       '{"@type":"Product","name":"Widget"}</script></head><body><h1>Widget</h1></body></html>')

    registry = JobRegistry(db)
    job_id = _sync_job_from_real_yaml(registry, GOODSMILE_YAML)
    registry.set_phase(job_id, JobPhase.COLLECT)
    ctx = CollectorContext.build(app_config, db)
    _seed_pre_existing_proof_state(ctx, job_id)

    old_run = ctx.run_history.start(job_id)
    ctx.run_history.finish(old_run, "completed", fetched_count=1, inserted_count=1, error_count=0)

    worker = Worker(app_config, worker_id="seed-guarantee-lifecycle-worker", db=db)
    registry.mark_queued(job_id)
    worker.run_one_job()

    runs = db.query("SELECT * FROM run_history WHERE job_id=? ORDER BY started_at ASC, rowid ASC", (job_id,))
    assert len(runs) == 2
    assert runs[-1]["run_id"] != old_run  # a genuinely new run, not the old one reused
    refreshed_old = db.query_one("SELECT * FROM run_history WHERE run_id=?", (old_run,))
    assert refreshed_old["fetched_count"] == 1  # untouched


# -- Test E: realistic production shape, via the real `jobs reseed` CLI --


def test_jobs_reseed_cli_reaches_real_production_shape(tmp_path):
    """Exercises the exact command scripts/run_goodsmile_phase1_batch1.sh
    now runs (`db-collector jobs reseed <job_id>`) as a real subprocess
    against a job created from the real production YAML -- proving the
    fix works end to end from a fresh CLI process, independent of any
    long-running worker's in-memory code.
    """
    home = tmp_path / "var"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"home_dir": str(home), "db_path": "reseed_cli_test.sqlite3"}), encoding="utf-8")

    cli = REPO_ROOT / ".venv" / "bin" / "db-collector"
    subprocess.run([str(cli), "--config", str(config_path), "migrate"], cwd=str(REPO_ROOT), check=True, capture_output=True)

    from db_collector_os.config import load_config
    from db_collector_os.database import Database

    cfg = load_config(str(config_path))
    db = Database(cfg.db_path)
    registry = JobRegistry(db)
    job_id = _sync_job_from_real_yaml(registry)
    registry.set_phase(job_id, JobPhase.COLLECT)
    ctx = CollectorContext.build(cfg, db)
    _seed_pre_existing_proof_state(ctx, job_id)
    db.close()

    result = subprocess.run(
        [str(cli), "--config", str(config_path), "jobs", "reseed", job_id],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["newly_queued_count"] == 1
    assert payload["newly_queued"] == [LIST_URL]

    db = Database(cfg.db_path)
    list_row = db.query_one("SELECT * FROM fetch_queue WHERE job_id=? AND url=?", (job_id, LIST_URL))
    assert list_row is not None
    assert list_row["status"] == "queued"
    product_rows = db.query("SELECT * FROM fetch_queue WHERE job_id=? AND url=?", (job_id, PRODUCT_URL))
    assert len(product_rows) == 1
    assert product_rows[0]["status"] == "done"
    db.close()


# -- Test F: no regression for other adapters -----------------------------


def _make_generic_job(jr: JobRegistry, collector_type: str, adapter: str, seed_urls: list[str]) -> str:
    return jr.create(
        job_name="regression check", category="x", target_db="x", target_table="entities",
        collector_type=collector_type, adapter=adapter, rate_limit=0.0,
        config={"seed_urls": seed_urls, "discovery": {"internal_links": False, "related_entities": False}},
    )


def test_other_adapters_seed_guarantee_unaffected(app_config, db):
    registry = JobRegistry(db)
    ctx = CollectorContext.build(app_config, db)

    cases = [
        (CollectorType.OFFICIAL_SITE, "sample_official_site", "https://shop.example.com/p1"),
        (CollectorType.LOCAL_BUSINESS, "sample_local_business", "https://biz.example.com/listing"),
        (CollectorType.PERSON, "sample_person", "https://people.example.com/profile"),
        (CollectorType.API, "sample_api", "https://api.example.com/products"),
    ]
    for collector_type, adapter_name, url in cases:
        job_id = _make_generic_job(registry, collector_type, adapter_name, [url])
        job = registry.get(job_id)
        newly_queued = ensure_seed_urls_queued(ctx, job)
        assert newly_queued == [url], f"adapter {adapter_name} regressed"
        assert ctx.fetch_queue.exists(job_id, url)
        # idempotent on a second call
        assert ensure_seed_urls_queued(ctx, job) == []
