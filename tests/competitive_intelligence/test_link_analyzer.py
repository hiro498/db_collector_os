from __future__ import annotations

from db_collector_os.competitive_intelligence.link_analyzer import compute_link_metrics
from db_collector_os.competitive_intelligence.repository.core import (
    CrawlRunRepository,
    CrawlUrlRepository,
    DomainRepository,
)
from db_collector_os.competitive_intelligence.repository.links import InternalLinkRepository
from db_collector_os.competitive_intelligence.repository.pages import PageRepository


def _make_page(db, domain, run_id, url, page_type="article"):
    crawl_url_id, _ = CrawlUrlRepository(db).add(run_id, domain["domain_id"], url, url, discovered_by="seed")
    page_id = PageRepository(db).upsert(crawl_url_id, run_id, domain["domain_id"], url, url,
                                         fetched_at="2024-01-01T00:00:00", page_type=page_type)
    return page_id


def test_compute_link_metrics_counts_inbound_and_outbound(db):
    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(domain["domain_id"], "https://example.jp/", "affiliate_domain",
                                            "affiliate_domain", "general")
    top = _make_page(db, domain, run_id, "https://example.jp/", page_type="top")
    a = _make_page(db, domain, run_id, "https://example.jp/a")
    b = _make_page(db, domain, run_id, "https://example.jp/b")

    links = InternalLinkRepository(db)
    links.replace_for_page(run_id, top, [
        {"target_url": "https://example.jp/a", "anchor_text": "a", "position": 0},
        {"target_url": "https://example.jp/b", "anchor_text": "b", "position": 1},
    ])
    links.replace_for_page(run_id, a, [
        {"target_url": "https://example.jp/b", "anchor_text": "b again", "position": 0},
    ])

    metrics = compute_link_metrics(db, run_id)

    assert metrics[top]["inbound_count"] == 0
    assert metrics[top]["outbound_count"] == 2
    assert metrics[a]["inbound_count"] == 1
    assert metrics[b]["inbound_count"] == 2  # linked from both top and a
    assert metrics[b]["outbound_count"] == 0


def test_compute_link_metrics_top_distance_via_bfs(db):
    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(domain["domain_id"], "https://example.jp/", "affiliate_domain",
                                            "affiliate_domain", "general")
    top = _make_page(db, domain, run_id, "https://example.jp/", page_type="top")
    a = _make_page(db, domain, run_id, "https://example.jp/a")
    b = _make_page(db, domain, run_id, "https://example.jp/b")

    links = InternalLinkRepository(db)
    links.replace_for_page(run_id, top, [{"target_url": "https://example.jp/a", "anchor_text": "a", "position": 0}])
    links.replace_for_page(run_id, a, [{"target_url": "https://example.jp/b", "anchor_text": "b", "position": 0}])

    metrics = compute_link_metrics(db, run_id)
    assert metrics[top]["top_distance"] == 0
    assert metrics[a]["top_distance"] == 1
    assert metrics[b]["top_distance"] == 2


def test_compute_link_metrics_flags_orphan_pages(db):
    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(domain["domain_id"], "https://example.jp/", "affiliate_domain",
                                            "affiliate_domain", "general")
    top = _make_page(db, domain, run_id, "https://example.jp/", page_type="top")
    orphan = _make_page(db, domain, run_id, "https://example.jp/orphan")
    # No internal_links rows reference `orphan` at all -- discovered (e.g.
    # via sitemap) but never linked to from any crawled page.

    metrics = compute_link_metrics(db, run_id)
    assert metrics[orphan]["is_orphan"] is True
    assert metrics[orphan]["top_distance"] is None
    assert metrics[top]["is_orphan"] is False  # the TOP page itself is never orphan


def test_compute_link_metrics_pagerank_sums_to_roughly_one(db):
    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(domain["domain_id"], "https://example.jp/", "affiliate_domain",
                                            "affiliate_domain", "general")
    top = _make_page(db, domain, run_id, "https://example.jp/", page_type="top")
    a = _make_page(db, domain, run_id, "https://example.jp/a")
    b = _make_page(db, domain, run_id, "https://example.jp/b")

    links = InternalLinkRepository(db)
    links.replace_for_page(run_id, top, [
        {"target_url": "https://example.jp/a", "anchor_text": "a", "position": 0},
        {"target_url": "https://example.jp/b", "anchor_text": "b", "position": 1},
    ])
    links.replace_for_page(run_id, a, [{"target_url": "https://example.jp/b", "anchor_text": "b", "position": 0}])
    links.replace_for_page(run_id, b, [{"target_url": "https://example.jp/", "anchor_text": "top", "position": 0}])

    metrics = compute_link_metrics(db, run_id)
    total = sum(m["pagerank"] for m in metrics.values())
    assert 0.9 < total < 1.1  # PageRank mass is conserved (allowing iteration rounding)
    # `b` receives links from both top and a -- it should rank at least as
    # high as `a`, which only receives one inbound link.
    assert metrics[b]["pagerank"] >= metrics[a]["pagerank"]


def test_compute_link_metrics_handles_empty_run(db):
    domain = DomainRepository(db).get_or_create("empty.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(domain["domain_id"], "https://empty.jp/", "affiliate_domain",
                                            "affiliate_domain", "general")
    assert compute_link_metrics(db, run_id) == {}
