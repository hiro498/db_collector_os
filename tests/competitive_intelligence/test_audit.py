from __future__ import annotations

from db_collector_os.competitive_intelligence.crawler.audit import recompute_audit
from db_collector_os.competitive_intelligence.enums import CrawlUrlStatus, ExclusionReason
from db_collector_os.competitive_intelligence.repository.core import (
    CrawlRunRepository,
    CrawlUrlRepository,
    DomainRepository,
)


def test_recompute_audit_counts_match_hand_built_crawl_urls(db):
    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(domain["domain_id"], "https://example.jp/", "affiliate_domain",
                                            "affiliate_domain", "general")
    urls = CrawlUrlRepository(db)

    def add(path: str, discovered_by: str = "internal_link") -> str:
        crawl_url_id, _ = urls.add(run_id, domain["domain_id"], f"https://example.jp{path}",
                                    f"https://example.jp{path}", discovered_by=discovered_by)
        return crawl_url_id

    completed_id = add("/a", discovered_by="sitemap")
    urls.set_status(completed_id, CrawlUrlStatus.COMPLETED)

    excluded_id = add("/b.png")
    urls.mark_excluded(excluded_id, ExclusionReason.NON_HTML_ASSET)

    failed_404_id = add("/c")
    urls.record_fetch_attempt(failed_404_id, CrawlUrlStatus.FAILED, http_status=404)

    still_pending_id = add("/d")  # never touched -- stays 'discovered'

    audit = recompute_audit(db, run_id)

    assert audit["discovered_total"] == 4
    assert audit["sitemap_discovered"] == 1
    assert audit["excluded_count"] == 1
    assert audit["count_404"] == 1
    assert audit["count_retry_failed"] == 1
    assert audit["unresolved_count"] == 1  # only /d is still pending
    assert audit["completion_rate"] == 0.75  # 3 of 4 URLs reached a terminal state

    run = CrawlRunRepository(db).get(run_id)
    assert run["discovered_total"] == 4  # persisted back onto the run row
    assert run["unresolved_count"] == 1


def test_recompute_audit_on_empty_run_has_completion_rate_one(db):
    domain = DomainRepository(db).get_or_create("empty.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(domain["domain_id"], "https://empty.jp/", "affiliate_domain",
                                            "affiliate_domain", "general")
    audit = recompute_audit(db, run_id)
    assert audit["discovered_total"] == 0
    assert audit["completion_rate"] == 1.0
