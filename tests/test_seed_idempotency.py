"""Regression tests for the Phase 1 batch #1 seed-idempotency bug: once a
job has moved past the BOOTSTRAP phase, config-added seed_urls used to be
silently dropped forever (checkpoint.state["seeded"] gated a one-time-only
enqueue that only ever ran from the BOOTSTRAP phase). In production this
meant expanding job_prod_figure_official_site's seed_urls to add the Good
Smile Scale Figure list, on top of an already-fetched single product URL,
never actually queued the list page -- the batch fetched 0 new pages.

fetch_queue.enqueue() is already idempotent per (job_id, url) -- these
tests confirm the pipeline now calls it every run_once() unconditionally
(not gated behind the one-time bootstrap flag), and that this never causes
an already-fetched ("done") seed to be duplicated or force-refetched.
"""

from __future__ import annotations

import json

import responses

from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType
from db_collector_os.worker import Worker

PRODUCT_A = "https://shop.example.com/product/a"
PRODUCT_B = "https://shop.example.com/product/b"


def make_job(jr: JobRegistry, seed_urls, **overrides) -> str:
    defaults = dict(
        job_name="Seed Idempotency Test", category="product", target_db="products", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="sample_official_site",
        rate_limit=0.0,  # tests drive multiple run_one_job() calls back-to-back within milliseconds
        config={"seed_urls": seed_urls, "discovery": {"internal_links": False, "related_entities": False}},
    )
    defaults.update(overrides)
    return jr.create(**defaults)


def _page(name: str) -> str:
    return (
        '<html><head><title>P</title><script type="application/ld+json">'
        f'{{"@type":"Product","name":"{name}"}}</script></head><body><h1>{name}</h1></body></html>'
    )


def _set_seed_urls(db, job_id: str, seed_urls: list[str]) -> None:
    row = db.query_one("SELECT config_json FROM jobs WHERE job_id=?", (job_id,))
    cfg = json.loads(row["config_json"] or "{}")
    cfg["seed_urls"] = seed_urls
    db.execute("UPDATE jobs SET config_json=? WHERE job_id=?", (json.dumps(cfg), job_id))


@responses.activate
def test_newly_added_seed_url_is_queued_after_bootstrap_already_completed(app_config, db):
    responses.add(responses.GET, "https://shop.example.com/robots.txt", status=404)
    responses.add(responses.GET, PRODUCT_A, status=200, content_type="text/html", body=_page("A"))

    jr = JobRegistry(db)
    job_id = make_job(jr, [PRODUCT_A])
    worker = Worker(app_config, worker_id="w1", db=db)

    jr.mark_queued(job_id)
    worker.run_one_job()

    checkpoint = worker.ctx.checkpoints.load(job_id)
    assert checkpoint["state"].get("seeded") is True  # bootstrap has already run and won't run again

    a_row = db.query_one("SELECT * FROM fetch_queue WHERE job_id=? AND url=?", (job_id, PRODUCT_A))
    assert a_row["status"] == "done"

    # Config grows a second seed URL (e.g. Good Smile's scale figure list
    # added on top of the already-proven single product URL). Item 4: B must
    # get queued even though bootstrap/"seeded" is long past.
    responses.add(responses.GET, PRODUCT_B, status=200, content_type="text/html", body=_page("B"))
    _set_seed_urls(db, job_id, [PRODUCT_A, PRODUCT_B])

    jr.mark_queued(job_id)
    worker.run_one_job()

    b_row = db.query_one("SELECT * FROM fetch_queue WHERE job_id=? AND url=?", (job_id, PRODUCT_B))
    assert b_row is not None, "newly added seed URL must be queued, not silently dropped"
    assert b_row["status"] == "done"  # item 6: new seed gets fetched


@responses.activate
def test_already_done_seed_is_not_duplicated_or_forced_to_refetch(app_config, db):
    responses.add(responses.GET, "https://shop.example.com/robots.txt", status=404)
    responses.add(responses.GET, PRODUCT_A, status=200, content_type="text/html", body=_page("A"))
    responses.add(responses.GET, PRODUCT_B, status=200, content_type="text/html", body=_page("B"))

    jr = JobRegistry(db)
    job_id = make_job(jr, [PRODUCT_A])
    worker = Worker(app_config, worker_id="w1", db=db)

    jr.mark_queued(job_id)
    worker.run_one_job()

    _set_seed_urls(db, job_id, [PRODUCT_A, PRODUCT_B])
    jr.mark_queued(job_id)
    outcome_holder = {}
    import db_collector_os.collectors.pipeline as pipeline_module
    real_run_once = pipeline_module.BaseCollector.run_once

    def spy(self, job):
        outcome = real_run_once(self, job)
        outcome_holder["outcome"] = outcome
        return outcome

    orig = pipeline_module.BaseCollector.run_once
    pipeline_module.BaseCollector.run_once = spy
    try:
        worker.run_one_job()
    finally:
        pipeline_module.BaseCollector.run_once = orig

    # item 5: only the new URL (B) was fetched this run -- A, already done,
    # was not duplicated in fetch_queue nor forced to refetch.
    assert outcome_holder["outcome"].fetched == 1

    a_rows = db.query("SELECT * FROM fetch_queue WHERE job_id=? AND url=?", (job_id, PRODUCT_A))
    assert len(a_rows) == 1, "enqueue() must stay idempotent per (job_id, url) -- no duplicate row for A"
    assert a_rows[0]["status"] == "done"
