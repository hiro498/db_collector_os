"""Realistic Good Smile Phase 1 regression test combining the run-lifecycle
and seed-idempotency fixes: exactly the production sequence that surfaced
both bugs.

1. A pre-existing single-product proof run: product A fetched, entity A
   created, checkpoint.state["seeded"] == True (mirrors the 2026-08-27
   single-product proof already on the VPS DB before Phase 1 batch #1).
2. The job config is then expanded to also seed the Scale Figure list (the
   actual Phase 1 change), on top of the still-configured product A URL.
3. A new execution (retry) must: create a brand-new run_id (not reuse
   proof's run_id), fetch the newly-added list page, discover product URLs
   from it, flow at least one new product candidate through to a fetch --
   all while leaving the original proof's run_history row and entity
   untouched.
"""

from __future__ import annotations

from pathlib import Path

import responses

from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType, RunStatus
from db_collector_os.worker import Worker

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOODSMILE_PATTERN = r"/en/product/(\d+)/|/en/scalefigure_list"
PRODUCT_URL = (
    "https://www.goodsmile.com/en/product/1141716/"
    "Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2Btoridamono"
)
LIST_URL = "https://www.goodsmile.com/en/scalefigure_list"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _make_job(jr: JobRegistry, seed_urls, **overrides) -> str:
    defaults = dict(
        job_name="Figure Official Site (Good Smile, lifecycle test)", category="figure",
        target_db="figure_official_site_test", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="figure_official_site",
        priority=50, schedule="@daily", max_pages=10, max_depth=2, concurrency=1, rate_limit=0.0,
        config={
            "seed_urls": seed_urls,
            "discovery": {
                "robots_seed_urls": ["https://www.goodsmile.com/"],
                "internal_links": True,
                "related_entities": True,
                "allowed_domains": ["www.goodsmile.com"],
                "product_url_pattern": GOODSMILE_PATTERN,
            },
            "phase1_conditions": {"queue_empty": True, "require_discovery_saturation": True, "min_entity_count": 1},
        },
    )
    defaults.update(overrides)
    return jr.create(**defaults)


@responses.activate
def test_expanding_seed_urls_after_single_product_proof_creates_new_run_and_fetches_list(app_config, db):
    responses.add(responses.GET, "https://www.goodsmile.com/robots.txt", status=404)
    responses.add(
        responses.GET, PRODUCT_URL, status=200, content_type="text/html",
        body=load_fixture("goodsmile_product_1141716.html"),
    )
    # goodsmile_product_1141716.html itself links to a "related item"
    # product page (/en/product/1141717/related-item), which also matches
    # GOODSMILE_PATTERN. With the same-run page-discovery-promotion fix,
    # that is discovered and fetched within step 1's own run (not deferred
    # to a later run) -- mock it so the proof run's own internal-links
    # discovery has somewhere real to land instead of hitting an
    # accidental unmocked-URL connection error.
    RELATED_URL = "https://www.goodsmile.com/en/product/1141717/related-item"
    responses.add(
        responses.GET, RELATED_URL, status=200, content_type="text/html",
        body=(
            '<html><head><meta charset="utf-8"><title>Related Item</title>'
            '<script type="application/ld+json">{"@context": "https://schema.org", '
            '"@type": "Product", "name": "Related Item Figure", "sku": "1141717", '
            '"brand": {"@type": "Brand", "name": "Good Smile Company"}}</script>'
            '</head><body><h1>Related Item Figure</h1></body></html>'
        ),
    )

    jr = JobRegistry(db)
    job_id = _make_job(jr, [PRODUCT_URL])
    worker = Worker(app_config, worker_id="lifecycle-proof-worker", db=db)

    # -- step 1: the pre-existing single-product proof -----------------------
    jr.mark_queued(job_id)
    worker.run_one_job()

    proof_run = db.query_one(
        "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1", (job_id,)
    )
    assert proof_run["status"] == RunStatus.COMPLETED
    # Same-run page-discovery-promotion fix: the product page's own
    # related-item link is discovered and fetched within this same run,
    # rather than only becoming fetchable on some later run -- see
    # collectors/pipeline.py BaseCollector._extract_records().
    assert proof_run["fetched_count"] == 2
    assert proof_run["inserted_count"] == 2
    proof_run_id = proof_run["run_id"]

    checkpoint = worker.ctx.checkpoints.load(job_id)
    assert checkpoint["state"].get("seeded") is True

    proof_entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert len(proof_entities) == 2
    proof_entity_id = next(e["entity_id"] for e in proof_entities if e["external_id"] == "1141716")

    # -- step 2: Phase 1 config expansion -- add the Scale Figure list as a --
    # -- second seed, on top of the already-fetched product URL. -------------
    responses.add(
        responses.GET, LIST_URL, status=200, content_type="text/html",
        body=load_fixture("goodsmile_scalefigure_list.html"),
    )
    for pid, slug, name in (
        ("2200481", "Nendoroid%2BSample%2BFigure", "Nendoroid Sample Figure"),
        ("3301592", "POP%2BUP%2BPARADE%2BSample", "POP UP PARADE Sample"),
    ):
        responses.add(
            responses.GET, f"https://www.goodsmile.com/en/product/{pid}/{slug}", status=200,
            content_type="text/html",
            body=(
                f'<html><head><meta charset="utf-8"><title>{name}</title>'
                f'<script type="application/ld+json">{{"@context": "https://schema.org", '
                f'"@type": "Product", "name": "{name}", "sku": "{pid}", '
                f'"brand": {{"@type": "Brand", "name": "Good Smile Company"}}}}</script>'
                f'</head><body><h1>{name}</h1></body></html>'
            ),
        )

    db.execute(
        "UPDATE jobs SET config_json=? WHERE job_id=?",
        (
            __import__("json").dumps({
                "seed_urls": [LIST_URL, PRODUCT_URL],
                "discovery": {
                    "robots_seed_urls": ["https://www.goodsmile.com/"],
                    "internal_links": True,
                    "related_entities": True,
                    "allowed_domains": ["www.goodsmile.com"],
                    "product_url_pattern": GOODSMILE_PATTERN,
                },
                "phase1_conditions": {
                    "queue_empty": True, "require_discovery_saturation": True, "min_entity_count": 1,
                },
            }),
            job_id,
        ),
    )

    # -- step 3: new execution (the Phase 1 batch #1 retry) -------------------
    jr.mark_queued(job_id)
    for _ in range(4):  # drain discovery -> promote candidates -> fetch, across a few worker ticks
        worker.run_one_job()
        jr.mark_queued(job_id)

    runs = db.query("SELECT * FROM run_history WHERE job_id=? ORDER BY started_at ASC, rowid ASC", (job_id,))
    assert len(runs) >= 2, "the retry must create at least one new run_history row"
    assert all(r["run_id"] != proof_run_id or r is runs[0] for r in runs)
    new_run_ids = {r["run_id"] for r in runs} - {proof_run_id}
    assert new_run_ids, "retry must not just reuse the proof's run_id"

    # proof row is completely untouched
    refreshed_proof = db.query_one("SELECT * FROM run_history WHERE run_id=?", (proof_run_id,))
    assert refreshed_proof["started_at"] == proof_run["started_at"]
    assert refreshed_proof["finished_at"] == proof_run["finished_at"]
    assert refreshed_proof["fetched_count"] == proof_run["fetched_count"]
    assert refreshed_proof["inserted_count"] == proof_run["inserted_count"]

    # the list page itself was fetched this time
    list_row = db.query_one("SELECT * FROM fetch_queue WHERE job_id=? AND url=?", (job_id, LIST_URL))
    assert list_row is not None
    assert list_row["status"] == "done"

    # at least one new product candidate flowed all the way through to a
    # fetched/known entity, beyond the original proof's single entity
    entities_after = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert len(entities_after) > 1
    assert any(e["entity_id"] == proof_entity_id for e in entities_after)  # proof entity preserved
