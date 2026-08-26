"""End-to-end smoke test: bootstrap -> discovery -> collect -> validation,
against a small mocked site (no real network), exercising discovery, fetch
queue, extraction, dedup, entity/evidence writes, and checkpoint/resume.
"""

from __future__ import annotations

import responses

from db_collector_os.collectors import CollectorContext, get_collector
from db_collector_os.database import Database
from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType, JobPhase
from db_collector_os.worker import Worker

PAGE_1 = """<html><head><title>Product 1</title>
<script type="application/ld+json">{"@type":"Product","name":"Widget One","sku":"W-1",
"brand":{"name":"Acme"},"offers":{"price":"10.00","priceCurrency":"USD"}}</script>
</head><body><h1>Widget One</h1><a href="https://shop.example.com/product/2">next</a></body></html>"""

PAGE_2 = """<html><head><title>Product 2</title>
<script type="application/ld+json">{"@type":"Product","name":"Widget Two","sku":"W-2",
"brand":{"name":"Acme"},"offers":{"price":"12.00","priceCurrency":"USD"}}</script>
</head><body><h1>Widget Two</h1></body></html>"""


def _mock_site():
    responses.add(responses.GET, "https://shop.example.com/robots.txt", body="User-agent: *\nAllow: /\n", status=200)
    responses.add(responses.GET, "https://shop.example.com/product/1", body=PAGE_1, status=200, content_type="text/html")
    responses.add(responses.GET, "https://shop.example.com/product/2", body=PAGE_2, status=200, content_type="text/html")


@responses.activate
def test_full_pipeline_creates_entities_and_advances_phase(app_config, db):
    _mock_site()

    jr = JobRegistry(db)
    job_id = jr.create(
        job_name="Shop Products", category="product", target_db="shop", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="sample_official_site",
        config={"seed_urls": ["https://shop.example.com/product/1"]}, max_pages=10, rate_limit=0,
    )

    worker = Worker(app_config, worker_id="smoke-test-worker", db=db)

    # Run the pipeline a handful of times through the real Worker entrypoint:
    # first run fetches page 1 and discovers page 2 as a candidate; a later
    # run promotes + fetches it.
    for _ in range(4):
        jr.mark_queued(job_id)
        worker.run_one_job()

    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    names = {e["name"] for e in entities}
    assert "Widget One" in names
    assert "Widget Two" in names

    evidence = db.query("SELECT * FROM evidence")
    assert len(evidence) > 0
    assert all(e["source_url"] for e in evidence)

    run_rows = db.query("SELECT * FROM run_history WHERE job_id=?", (job_id,))
    assert len(run_rows) == 4
    assert all(r["status"] == "completed" for r in run_rows)

    job_final = jr.get(job_id)
    assert job_final["phase"] in (JobPhase.DISCOVERY, JobPhase.COLLECT, JobPhase.VALIDATION, JobPhase.PHASE1_COMPLETE)


@responses.activate
def test_checkpoint_survives_simulated_restart(app_config, tmp_home):
    _mock_site()
    db_path = tmp_home / "restart_test.sqlite3"

    db1 = Database(db_path)
    jr1 = JobRegistry(db1)
    job_id = jr1.create(
        job_name="Shop Products", category="product", target_db="shop", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="sample_official_site",
        config={"seed_urls": ["https://shop.example.com/product/1"]}, max_pages=10, rate_limit=0,
    )
    ctx1 = CollectorContext.build(app_config, db1)
    jr1.mark_queued(job_id)
    jr1.claim_queued(job_id)
    job = jr1.get(job_id)
    collector1 = get_collector(job["collector_type"], ctx1)
    collector1.run_once(job)
    # Simulate a crash: the job is left in 'running' with a checkpoint saved,
    # never reaching jr.finish().
    db1.close()

    # "Process restart": open a fresh Database/connection against the same file.
    db2 = Database(db_path)
    jr2 = JobRegistry(db2)
    job_after_crash = jr2.get(job_id)
    assert job_after_crash["status"] == "running"

    jr2.reset_stale_running(job_id)  # what Worker.recover_stale_jobs() does
    assert jr2.get(job_id)["status"] == "retry"

    entities_before = db2.query("SELECT COUNT(*) AS n FROM entities WHERE job_id=?", (job_id,))[0]["n"]
    assert entities_before >= 1  # page 1 was already committed before the "crash"

    ctx2 = CollectorContext.build(app_config, db2)
    jr2.mark_queued(job_id)
    jr2.claim_queued(job_id)
    job = jr2.get(job_id)
    collector2 = get_collector(job["collector_type"], ctx2)
    collector2.run_once(job)  # resumes and fetches page 2 without re-fetching page 1

    entities_after = db2.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert len(entities_after) == 2
    db2.close()
