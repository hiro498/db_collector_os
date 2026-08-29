"""Regression test for the Good Smile Phase 1 Batch #2 "one URL = one run"
bug: with a single domain and rate_limit > 0, _drain_fetch_queue() used to
fetch exactly one page then immediately give up (the domain becomes
not-ready the instant the first request is recorded, and the loop treated
"not ready right now" identically to "nothing left to do"), no matter how
large max_pages was. Opt-in (config.max_drain_wait_seconds) fix: the drain
loop now waits out short per-domain rate-limit gaps so one run_once() call
can process up to max_pages, exactly like the job's own "max_pages" ceiling
promises.
"""

from __future__ import annotations

import responses

from db_collector_os.collectors import CollectorContext, get_collector
from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType

DOMAIN = "https://shop.example.com"


def _page(name: str) -> str:
    return (
        '<html><head><title>P</title><script type="application/ld+json">'
        f'{{"@type":"Product","name":"{name}"}}</script></head><body><h1>{name}</h1></body></html>'
    )


def _make_job(jr: JobRegistry, urls: list[str], *, max_pages: int, rate_limit: float, max_drain_wait_seconds: float) -> str:
    return jr.create(
        job_name="Drain Wait Test", category="product", target_db="products", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="sample_official_site",
        max_pages=max_pages, rate_limit=rate_limit,
        config={
            "seed_urls": urls,
            "discovery": {"internal_links": False, "related_entities": False},
            "max_drain_wait_seconds": max_drain_wait_seconds,
        },
    )


@responses.activate
def test_one_run_processes_multiple_pages_despite_same_domain_rate_limit(app_config, db):
    urls = [f"{DOMAIN}/product/{i}" for i in range(4)]
    jr = JobRegistry(db)
    # A short rate_limit keeps this test fast (a few hundred ms of real
    # sleeping) while still exercising the real per-domain wait mechanism --
    # production uses a longer rate_limit with a correspondingly larger
    # max_drain_wait_seconds budget (see config/jobs/prod_figure_official_site.yaml).
    job_id = _make_job(jr, urls, max_pages=4, rate_limit=0.3, max_drain_wait_seconds=5.0)

    responses.add(responses.GET, f"{DOMAIN}/robots.txt", status=404)
    for i, url in enumerate(urls):
        responses.add(responses.GET, url, status=200, content_type="text/html", body=_page(f"W{i}"))

    ctx = CollectorContext.build(app_config, db)
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    job = jr.get(job_id)
    collector = get_collector(job["collector_type"], ctx)
    outcome = collector.run_once(job)

    assert outcome.fetched == 4  # all 4 pages, one run_once() call
    assert outcome.inserted == 4
    assert ctx.fetch_queue.pending_count(job_id) == 0


@responses.activate
def test_drain_wait_still_respects_max_pages_cap(app_config, db):
    urls = [f"{DOMAIN}/product/{i}" for i in range(6)]
    jr = JobRegistry(db)
    job_id = _make_job(jr, urls, max_pages=3, rate_limit=0.2, max_drain_wait_seconds=5.0)

    responses.add(responses.GET, f"{DOMAIN}/robots.txt", status=404)
    for i, url in enumerate(urls):
        responses.add(responses.GET, url, status=200, content_type="text/html", body=_page(f"W{i}"))

    ctx = CollectorContext.build(app_config, db)
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    job = jr.get(job_id)
    collector = get_collector(job["collector_type"], ctx)
    outcome = collector.run_once(job)

    assert outcome.fetched == 3  # max_pages honored even with drain-wait enabled
    assert ctx.fetch_queue.pending_count(job_id) == 3  # the rest waits for a later run


@responses.activate
def test_default_behavior_unchanged_when_max_drain_wait_not_set(app_config, db):
    """max_drain_wait_seconds defaults to 0 -- every job that doesn't opt
    in keeps today's exact behavior: one rate-limited domain miss ends the
    drain loop for this run immediately, no sleeping."""
    urls = [f"{DOMAIN}/product/{i}" for i in range(3)]
    jr = JobRegistry(db)
    job_id = jr.create(
        job_name="No Drain Wait", category="product", target_db="products", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="sample_official_site",
        max_pages=10, rate_limit=30.0,
        config={"seed_urls": urls, "discovery": {"internal_links": False, "related_entities": False}},
    )

    responses.add(responses.GET, f"{DOMAIN}/robots.txt", status=404)
    for i, url in enumerate(urls):
        responses.add(responses.GET, url, status=200, content_type="text/html", body=_page(f"W{i}"))

    ctx = CollectorContext.build(app_config, db)
    jr.mark_queued(job_id)
    jr.claim_queued(job_id)
    job = jr.get(job_id)
    collector = get_collector(job["collector_type"], ctx)
    outcome = collector.run_once(job)

    assert outcome.fetched == 1  # unchanged pre-existing behavior
    assert ctx.fetch_queue.pending_count(job_id) == 2
