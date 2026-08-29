"""Regression tests for the same-run page-discovery-promotion fix (Good Smile
Phase 1 Batch #1): a page fetched during BaseCollector._drain_fetch_queue()
(e.g. the scalefigure_list listing page) discovers new product candidates via
DiscoveryEngine.discover_from_page(); those candidates must become eligible
for promotion into fetch_queue and get fetched within the SAME bounded run,
not only on some later run_once() call. Also covers the accompanying metrics
fix: DiscoveryEngine._save_candidates() now returns only genuinely-new
candidates (via CandidateStore.add()'s own (candidate_id, created) result,
previously discarded), so RunOutcome.discovered / run_history.discovered_count
/ discovery_runs.new_candidates reflect real new candidates, never a bare
count of every observed (possibly duplicate) link.

All fixtures reuse the existing Good Smile reconstructions (see their own
header comments in tests/fixtures/) -- this environment has no outbound web
access to www.goodsmile.com; every request is served by `responses` mocks.
"""

from __future__ import annotations

from pathlib import Path

import responses

from db_collector_os.candidates import CandidateStore
from db_collector_os.collectors import CollectorContext, get_collector
from db_collector_os.database import new_id
from db_collector_os.job_registry import JobRegistry, now_iso
from db_collector_os.models.enums import CandidateStatus, CollectorType
from db_collector_os.worker import Worker

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOODSMILE_PATTERN = r"/en/product/(\d+)/|/en/scalefigure_list"
LIST_URL = "https://www.goodsmile.com/en/scalefigure_list"
LIST_PAGE2_URL = "https://www.goodsmile.com/en/scalefigure_list?page=2"
LIST_PAGE1_BACKLINK_URL = "https://www.goodsmile.com/en/scalefigure_list?page=1"
PRODUCT_1141716_URL = (
    "https://www.goodsmile.com/en/product/1141716/"
    "Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2Btoridamono"
)


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _make_job(jr: JobRegistry, **overrides) -> str:
    defaults = dict(
        job_name="Figure Official Site (Good Smile, same-run test)", category="figure",
        target_db="figure_official_site_test", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="figure_official_site",
        priority=50, schedule="@daily", max_pages=30, max_depth=2, concurrency=1, rate_limit=0.0,
        config={
            "seed_urls": [LIST_URL],
            "discovery": {
                "internal_links": True,
                "related_entities": True,
                "allowed_domains": ["www.goodsmile.com"],
                "product_url_pattern": GOODSMILE_PATTERN,
            },
        },
    )
    defaults.update(overrides)
    return jr.create(**defaults)


def _product_html(product_id: str, name: str, brand: str = "Good Smile Company") -> str:
    return (
        f'<html><head><meta charset="utf-8"><title>{name}</title>'
        f'<script type="application/ld+json">{{"@context": "https://schema.org", '
        f'"@type": "Product", "name": "{name}", "sku": "{product_id}", '
        f'"brand": {{"@type": "Brand", "name": "{brand}"}}}}</script>'
        f'</head><body><h1>{name}</h1></body></html>'
    )


def _mock_robots():
    responses.add(responses.GET, "https://www.goodsmile.com/robots.txt", status=404)


def _mock_list_page():
    responses.add(
        responses.GET, LIST_URL, status=200, content_type="text/html",
        body=load_fixture("goodsmile_scalefigure_list.html"),
    )


def _mock_all_real_products():
    """The 5 distinct real product IDs the list fixture links to (the
    duplicate 1141716 slug is suppressed before ever being fetched -- see
    test D), plus product 1141716's own detail-page "related item" link
    (goodsmile_product_1141716.html links to /en/product/1141717/), which
    is itself a legitimate same-run page discovery."""
    responses.add(
        responses.GET, PRODUCT_1141716_URL, status=200, content_type="text/html",
        body=load_fixture("goodsmile_product_1141716.html"),
    )
    responses.add(
        responses.GET, "https://www.goodsmile.com/en/product/1141717/related-item",
        status=200, content_type="text/html", body=_product_html("1141717", "Related Item Figure"),
    )
    for pid, slug, name in (
        ("2200481", "Nendoroid%2BSample%2BFigure", "Nendoroid Sample Figure"),
        ("3301592", "POP%2BUP%2BPARADE%2BSample", "POP UP PARADE Sample"),
        ("4402703", "figma%2BSample%2BFigure", "figma Sample Figure"),
        ("5503814", "Max%2BFactory%2BScale%2BSample", "Max Factory Scale Sample"),
    ):
        responses.add(
            responses.GET, f"https://www.goodsmile.com/en/product/{pid}/{slug}", status=200,
            content_type="text/html", body=_product_html(pid, name),
        )


def _mock_page2_and_its_products():
    responses.add(
        responses.GET, LIST_PAGE2_URL, status=200, content_type="text/html",
        body=load_fixture("goodsmile_scalefigure_list_page2.html"),
    )
    # page2's own "previous" link (?page=1) is a distinct URL from the plain
    # seed and is itself pattern-matching -- mock it with the pre-existing
    # empty-list fixture so the discovery chain terminates cleanly instead
    # of hitting an unmocked-URL error.
    responses.add(
        responses.GET, LIST_PAGE1_BACKLINK_URL, status=200, content_type="text/html",
        body=load_fixture("goodsmile_scalefigure_list_empty.html"),
    )
    for pid, slug, name in (
        ("6604925", "another-good-smile-figure", "Another Figure GSC"),
        ("7706036", "another-max-factory-figure", "Another Figure MF"),
    ):
        responses.add(
            responses.GET, f"https://www.goodsmile.com/en/product/{pid}/{slug}", status=200,
            content_type="text/html", body=_product_html(pid, name),
        )


def _mock_full_closed_graph():
    """Every URL reachable from the list fixture graph is mocked -- a fully
    closed graph, zero unmocked-URL errors possible."""
    _mock_robots()
    _mock_list_page()
    _mock_all_real_products()
    _mock_page2_and_its_products()


def _run_once(app_config, db, job_id):
    ctx = CollectorContext.build(app_config, db)
    jr = JobRegistry(db)
    jr.claim_queued(job_id)
    job = jr.get(job_id)
    collector = get_collector(job["collector_type"], ctx)
    return collector.run_once(job), ctx


# ---------------------------------------------------------------------------
# A. listing seed fetched -> matching product links -> candidates created ->
#    promoted -> product URLs fetched in the SAME run.
# ---------------------------------------------------------------------------

@responses.activate
def test_a_listing_discovered_products_fetched_within_same_run(app_config, db):
    _mock_full_closed_graph()
    jr = JobRegistry(db)
    job_id = _make_job(jr)
    jr.mark_queued(job_id)

    outcome, ctx = _run_once(app_config, db, job_id)

    # Everything (list + page2 + page2's own "previous" backlink + 8
    # distinct products, including 1141716's own "related item" link)
    # fetched in ONE run_once() call -- previously this required a separate
    # later run for every page-discovered candidate.
    assert outcome.errors == 0
    assert outcome.fetched == 11  # list(1) + page2(1) + page1-backlink(1) + 8 real products
    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert len(entities) == 8
    names = {e["name"] for e in entities}
    assert "Rikka Takarada & Akane Shinjo feat. toridamono" in names
    assert any("Nendoroid" in n for n in names)
    assert any("Another Figure" in n for n in names)


# ---------------------------------------------------------------------------
# B. max_pages remains a hard cap even when the listing discovers many links.
# ---------------------------------------------------------------------------

@responses.activate
def test_b_max_pages_still_caps_total_fetches_this_run(app_config, db):
    _mock_full_closed_graph()
    jr = JobRegistry(db)
    job_id = _make_job(jr, max_pages=3)
    jr.mark_queued(job_id)

    outcome, ctx = _run_once(app_config, db, job_id)

    assert outcome.fetched == 3  # never more than max_pages, even though many more were discovered
    assert ctx.fetch_queue.pending_count(job_id) > 0  # the rest stayed queued for a later run


# ---------------------------------------------------------------------------
# C. duplicate product links (same page) -> no duplicate fetch_queue rows.
# ---------------------------------------------------------------------------

@responses.activate
def test_c_duplicate_product_link_on_same_page_not_double_queued(app_config, db):
    _mock_full_closed_graph()
    jr = JobRegistry(db)
    job_id = _make_job(jr)
    jr.mark_queued(job_id)

    _run_once(app_config, db, job_id)

    rows = db.query(
        "SELECT * FROM fetch_queue WHERE job_id=? AND url LIKE '%1141716%'", (job_id,)
    )
    assert len(rows) == 1  # the list fixture links to product 1141716 via two different slugs


# ---------------------------------------------------------------------------
# D. same product ID, different slugs -> stable_id/fingerprint dedup holds
#    at the candidate level too.
# ---------------------------------------------------------------------------

@responses.activate
def test_d_same_product_id_different_slugs_dedups_to_one_candidate(app_config, db):
    _mock_full_closed_graph()
    jr = JobRegistry(db)
    job_id = _make_job(jr)
    jr.mark_queued(job_id)

    _run_once(app_config, db, job_id)

    rows = db.query(
        "SELECT * FROM entity_candidates WHERE job_id=? AND fingerprint LIKE '%1141716%'", (job_id,)
    )
    assert len(rows) == 1
    # the canonical slug (first one on the page) is the one that won the race
    assert rows[0]["url"] == PRODUCT_1141716_URL


# ---------------------------------------------------------------------------
# E. disallowed-domain link -> never promoted/fetched.
# ---------------------------------------------------------------------------

@responses.activate
def test_e_disallowed_domain_link_never_promoted_or_fetched(app_config, db):
    _mock_full_closed_graph()
    jr = JobRegistry(db)
    job_id = _make_job(jr)
    jr.mark_queued(job_id)

    _run_once(app_config, db, job_id)

    candidate_rows = db.query(
        "SELECT * FROM entity_candidates WHERE job_id=? AND url LIKE '%not-goodsmile%'", (job_id,)
    )
    queue_rows = db.query(
        "SELECT * FROM fetch_queue WHERE job_id=? AND url LIKE '%not-goodsmile%'", (job_id,)
    )
    assert candidate_rows == []
    assert queue_rows == []


# ---------------------------------------------------------------------------
# F. link not matching product_url_pattern -> never promoted/fetched
#    (includes /search, explicitly required to stay excluded).
# ---------------------------------------------------------------------------

@responses.activate
def test_f_non_matching_pattern_links_never_promoted_or_fetched(app_config, db):
    _mock_full_closed_graph()
    jr = JobRegistry(db)
    job_id = _make_job(jr)
    jr.mark_queued(job_id)

    _run_once(app_config, db, job_id)

    queue_urls = {r["url"] for r in db.query("SELECT url FROM fetch_queue WHERE job_id=?", (job_id,))}
    candidate_urls = {r["url"] for r in db.query("SELECT url FROM entity_candidates WHERE job_id=?", (job_id,))}
    for excluded in ("/about", "/contact", "/cart", "/account", "/search", "/privacy"):
        assert not any(excluded in u for u in queue_urls), excluded
        assert not any(excluded in u for u in candidate_urls), excluded


# ---------------------------------------------------------------------------
# G. listing page without Product JSON-LD -> skipped as entity, no review
#    noise, even once it is fetched as part of this same run.
# ---------------------------------------------------------------------------

@responses.activate
def test_g_listing_page_itself_never_becomes_entity_or_review_noise(app_config, db):
    _mock_full_closed_graph()
    jr = JobRegistry(db)
    job_id = _make_job(jr)
    jr.mark_queued(job_id)

    _run_once(app_config, db, job_id)

    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert not any(e["name"] in ("Scale Figures",) for e in entities)
    review_rows = db.query("SELECT * FROM review_queue WHERE job_id=?", (job_id,))
    assert review_rows == []  # fully closed/mocked graph -> nothing should need manual review


# ---------------------------------------------------------------------------
# H. a pre-existing candidate from an earlier run/pass is still promotable
#    and fetchable by the corrected run (production has 487 of these).
# ---------------------------------------------------------------------------

@responses.activate
def test_h_pre_existing_candidate_from_earlier_run_is_promoted_and_fetched(app_config, db):
    _mock_robots()
    responses.add(
        responses.GET, "https://www.goodsmile.com/en/product/8800000/preexisting-candidate",
        status=200, content_type="text/html", body=_product_html("8800000", "Pre-existing Candidate Figure"),
    )

    jr = JobRegistry(db)
    # No seed_urls at all -- the only thing to promote is the pre-existing
    # candidate, simulating production's 487 already-discovered candidates.
    job_id = _make_job(jr, config={
        "seed_urls": [],
        "discovery": {"internal_links": True, "related_entities": True,
                      "allowed_domains": ["www.goodsmile.com"], "product_url_pattern": GOODSMILE_PATTERN},
    })

    ctx = CollectorContext.build(app_config, db)
    CandidateStore(db).add(
        job_id=job_id, entity_type="figure", name=None, normalized_name=None,
        url="https://www.goodsmile.com/en/product/8800000/preexisting-candidate",
        source_url="https://www.goodsmile.com/en/product/8800000/preexisting-candidate",
        discovery_method="internal_link", fingerprint="figure:8800000", confidence=0.6,
    )
    row = db.query_one("SELECT * FROM entity_candidates WHERE job_id=?", (job_id,))
    assert row["status"] == CandidateStatus.NEW

    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    job = jr.get(job_id)
    collector = get_collector(job["collector_type"], ctx)
    outcome = collector.run_once(job)

    assert outcome.fetched == 1
    assert outcome.inserted == 1
    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    assert any(e["name"] == "Pre-existing Candidate Figure" for e in entities)


# ---------------------------------------------------------------------------
# I. page-discovery metrics: run_history.discovered_count and
#    discovery_runs.new_candidates no longer report a false zero when
#    genuinely new candidates were discovered from a fetched page.
# ---------------------------------------------------------------------------

@responses.activate
def test_i_page_discovery_metrics_are_no_longer_false_zero(app_config, db):
    _mock_full_closed_graph()
    jr = JobRegistry(db)
    job_id = _make_job(jr)
    jr.mark_queued(job_id)

    worker = Worker(app_config, worker_id="same-run-metrics-worker", db=db)
    worker.run_one_job()

    run_row = db.query_one(
        "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1", (job_id,)
    )
    disc_row = db.query_one(
        "SELECT * FROM discovery_runs WHERE run_id=? ORDER BY created_at DESC LIMIT 1", (run_row["run_id"],)
    )

    # The bug: run_history.discovered_count stayed 0 while discovery_runs.
    # discovered_total (a cumulative, all-time count) was already nonzero.
    # Both must now reflect that genuinely new candidates were found this run.
    assert run_row["discovered_count"] > 0
    assert disc_row["new_candidates"] > 0
    assert disc_row["new_candidates"] == run_row["discovered_count"]
    assert disc_row["discovered_total"] >= disc_row["new_candidates"]


# ---------------------------------------------------------------------------
# I2. re-running an already-fully-processed job reports 0 new candidates
#     (not a false positive) -- discovery observing the same links twice
#     must not inflate discovered_count on the second pass.
# ---------------------------------------------------------------------------

@responses.activate
def test_i2_rerun_after_full_discovery_reports_zero_new_candidates(app_config, db):
    _mock_full_closed_graph()
    jr = JobRegistry(db)
    job_id = _make_job(jr)
    jr.mark_queued(job_id)
    worker = Worker(app_config, worker_id="same-run-metrics-worker-2", db=db)
    worker.run_one_job()

    jr.mark_queued(job_id)
    worker.run_one_job()

    run_row = db.query_one(
        "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1", (job_id,)
    )
    assert run_row["discovered_count"] == 0
