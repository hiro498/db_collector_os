"""Crawl Engine: convergence crawling for affiliate_domain, single-page
processing for advertiser_lp, resumable state machine, safe stop
(spec sections 5, 6, 12, 13, 45).
"""

from __future__ import annotations

import logging
import time

from ...database import Database
from ...fetching.client import FetchEngine
from ...fetching.rate_limiter import DomainRateLimiter
from ...job_registry import now_iso
from ..enums import CrawlRunStatus, CrawlUrlStatus, ExclusionReason, InputMode
from ..fetcher import JSFallbackFetcher, fetch_page
from ..keyword.pipeline import finalize_run, score_and_store_page
from ..monetization import classify_cta_affiliate, classify_outbound_link, compute_monetization
from ..page_classifier import classify, is_seo_analysis_target
from ..parser import ParsedPage, detect_and_mark_boilerplate, parse_page
from ..repository.core import CrawlRunRepository, CrawlUrlRepository, DomainRepository
from ..repository.links import CtaRepository, InternalLinkRepository, OutboundLinkRepository
from ..repository.pages import PageElementRepository, PageRepository
from ..url_tools import classify_non_crawlable, extract_host, is_pagination_url, normalize_url
from . import audit as audit_mod
from . import discovery as discovery_mod

logger = logging.getLogger("db_collector_os.competitive_intelligence.crawler")

# A runaway-loop guard, not a page-count cap (spec section 5 explicitly
# forbids a page limit for affiliate_domain crawls): only ever trips on a
# pathological site (e.g. an infinite pagination trap), and when it does
# the run is marked stopped/not-converged rather than falsely completed.
MAX_CONVERGENCE_ITERATIONS = 500
MAX_FETCH_ATTEMPTS = 3


class CrawlEngine:
    def __init__(self, db: Database, user_agent: str, js_fallback: JSFallbackFetcher | None = None):
        self.db = db
        self.fetch_engine = FetchEngine(user_agent=user_agent)
        self.rate_limiter = DomainRateLimiter(db)
        self.js_fallback = js_fallback
        self.domains = DomainRepository(db)
        self.runs = CrawlRunRepository(db)
        self.urls = CrawlUrlRepository(db)
        self.pages = PageRepository(db)
        self.elements = PageElementRepository(db)
        self.internal_links = InternalLinkRepository(db)
        self.outbound_links = OutboundLinkRepository(db)
        self.ctas = CtaRepository(db)

    # -- entry points --------------------------------------------------------

    def start_advertiser_lp(self, url: str, requested_mode: str, vertical: str = "general") -> str:
        normalized = normalize_url(url)
        host = extract_host(normalized)
        domain = self.domains.get_or_create(host, target_type=InputMode.ADVERTISER_LP, vertical=vertical)
        crawl_run_id = self.runs.create(domain["domain_id"], url, requested_mode, InputMode.ADVERTISER_LP, vertical)
        self.urls.add(crawl_run_id, domain["domain_id"], url, normalized, discovered_by="seed")
        self._drain(crawl_run_id, host, single_page=True)
        return crawl_run_id

    def start_affiliate_domain(self, url: str, requested_mode: str, vertical: str = "general") -> str:
        normalized = normalize_url(url)
        host = extract_host(normalized)
        domain = self.domains.get_or_create(host, target_type=InputMode.AFFILIATE_DOMAIN, vertical=vertical)
        crawl_run_id = self.runs.create(
            domain["domain_id"], url, requested_mode, InputMode.AFFILIATE_DOMAIN, vertical
        )
        self.urls.add(crawl_run_id, domain["domain_id"], url, normalized, discovered_by="seed")

        for item in discovery_mod.discover_sitemap_urls(self.fetch_engine, normalized):
            self.urls.add(
                crawl_run_id, domain["domain_id"], item["url"], normalize_url(item["url"]),
                discovered_by=item["discovered_by"],
            )
        self.runs.update_audit(crawl_run_id, sitemap_phase_done=1, sitemap_index_phase_done=1)

        self._drain(crawl_run_id, host, single_page=False)
        return crawl_run_id

    def resume(self, crawl_run_id: str) -> str:
        run = self.runs.get(crawl_run_id)
        if not run:
            raise ValueError(f"no such crawl_run: {crawl_run_id}")
        self.runs.clear_stop(crawl_run_id)
        self.runs.set_status(crawl_run_id, CrawlRunStatus.RUNNING)
        domain = self.domains.get(run["domain_id"])
        self._drain(crawl_run_id, domain["domain"], single_page=(run["input_mode"] == InputMode.ADVERTISER_LP))
        return crawl_run_id

    def request_stop(self, crawl_run_id: str) -> None:
        self.runs.request_stop(crawl_run_id)

    def reanalyze(self, crawl_run_id: str) -> None:
        """REANALYZE (section 45): re-run classification + keyword scoring
        from stored page_elements, without any network access."""
        run = self.runs.get(crawl_run_id)
        if not run:
            raise ValueError(f"no such crawl_run: {crawl_run_id}")
        detect_and_mark_boilerplate(self.db, crawl_run_id)
        for page in self.pages.list_for_run(crawl_run_id, limit=1_000_000):
            elements = self.elements.list_for_page(page["page_id"])
            crawl_url = self.urls.get(page["crawl_url_id"])
            force_exclude = bool(crawl_url and crawl_url["is_canonical_duplicate"])
            self._classify_and_score(page, elements, force_exclude=force_exclude)
        finalize_run(self.db, crawl_run_id)
        audit_mod.recompute_audit(self.db, crawl_run_id)

    # -- processing loop ------------------------------------------------------

    def _drain(self, crawl_run_id: str, host: str, single_page: bool) -> None:
        iterations = 0
        while iterations < MAX_CONVERGENCE_ITERATIONS:
            iterations += 1
            if self.runs.is_stop_requested(crawl_run_id):
                self._stop_safely(crawl_run_id)
                return

            pending = self.urls.list_by_status(
                crawl_run_id, (CrawlUrlStatus.DISCOVERED, CrawlUrlStatus.QUEUED), limit=200
            )
            if not pending:
                break

            new_discovered = 0
            for crawl_url in pending:
                if self.runs.is_stop_requested(crawl_run_id):
                    self._stop_safely(crawl_run_id)
                    return
                new_discovered += self._process_one(crawl_run_id, crawl_url, host, single_page)

            self.internal_links.resolve_targets(crawl_run_id)
            detect_and_mark_boilerplate(self.db, crawl_run_id)
            audit_mod.recompute_audit(self.db, crawl_run_id)

            if single_page or new_discovered == 0:
                break

        self._finalize(crawl_run_id, iterations)

    def _stop_safely(self, crawl_run_id: str) -> None:
        """Called only between URLs (never mid-fetch/mid-parse), per spec
        section 13's "safe processing boundary" requirement."""
        self.runs.set_status(crawl_run_id, CrawlRunStatus.STOPPED)
        audit_mod.recompute_audit(self.db, crawl_run_id)

    def _process_one(self, crawl_run_id: str, crawl_url: dict, host: str, single_page: bool) -> int:
        crawl_url_id = crawl_url["crawl_url_id"]
        url = crawl_url["url"]

        exclusion = None if single_page else classify_non_crawlable(url, host)
        if exclusion:
            self.urls.mark_excluded(crawl_url_id, exclusion)
            return 0

        allowed, wait = self.rate_limiter.is_allowed(host)
        if not allowed:
            time.sleep(min(wait, 5.0))
        self.rate_limiter.record_request(host)

        result = fetch_page(self.fetch_engine, url, self.js_fallback)
        if not result.ok:
            self._record_fetch_failure(crawl_url, result)
            self.rate_limiter.record_error(host)
            return 0
        self.rate_limiter.record_success(host)

        parsed = parse_page(result.html or "", url)
        canonical = parsed.canonical_url or url
        self.urls.record_fetch_attempt(
            crawl_url_id, CrawlUrlStatus.FETCHED, http_status=result.http_status,
            redirect_to=result.final_url if result.final_url and result.final_url != url else None,
            canonical_url=canonical,
        )

        domain_id = crawl_url["domain_id"]
        fetched_at = now_iso()
        page_id = self.pages.upsert(
            crawl_url_id, crawl_run_id, domain_id, url, crawl_url["normalized_url"], fetched_at=fetched_at,
            title=parsed.title, meta_description=parsed.meta_description, meta_keywords=parsed.meta_keywords,
            canonical_url=canonical, robots_meta=parsed.robots_meta,
            published_at=parsed.published_at, updated_at_source=parsed.updated_at_source,
        )
        self.elements.replace_all(page_id, parsed.elements)
        self.internal_links.replace_for_page(crawl_run_id, page_id, parsed.internal_links)
        outbound = [{**link, **classify_outbound_link(link["target_domain"])} for link in parsed.outbound_links]
        self.outbound_links.replace_for_page(crawl_run_id, page_id, outbound)
        ctas = [
            {**cta, "affiliate_detected": classify_cta_affiliate(cta.get("target_domain"))}
            for cta in parsed.ctas
        ]
        self.ctas.replace_for_page(page_id, ctas)

        is_canonical_dup = bool(parsed.canonical_url) and normalize_url(parsed.canonical_url) != crawl_url["normalized_url"]
        if is_canonical_dup:
            self.urls.set_canonical_duplicate(crawl_url_id)
        self.urls.set_indexable(crawl_url_id, parsed.indexable)
        self.urls.set_pagination(crawl_url_id, is_pagination_url(url))
        self.urls.set_status(crawl_url_id, CrawlUrlStatus.PARSED)

        page = self.pages.get(page_id)
        self._classify_and_score(
            page, parsed.elements, parsed=parsed, outbound_links=outbound, ctas=ctas,
            force_exclude=is_canonical_dup,
        )
        self.urls.set_status(crawl_url_id, CrawlUrlStatus.COMPLETED)

        if single_page:
            return 0
        return self._discover_from_page(crawl_run_id, domain_id, url, parsed, host)

    def _classify_and_score(
        self, page: dict, elements: list[dict], parsed: ParsedPage | None = None,
        outbound_links: list[dict] | None = None, ctas: list[dict] | None = None,
        force_exclude: bool = False,
    ) -> None:
        page_id = page["page_id"]
        outbound_links = outbound_links if outbound_links is not None else self.outbound_links.list_for_page(page_id)
        ctas = ctas if ctas is not None else self.ctas.list_for_page(page_id)
        affiliate_count = sum(1 for o in outbound_links if o["link_type"] == "affiliate")
        affiliate_ratio = affiliate_count / len(outbound_links) if outbound_links else 0.0
        json_ld = parsed.json_ld if parsed is not None else []
        title = parsed.title if parsed is not None else page.get("title")

        page_type, confidence = classify(elements, json_ld, title, page["url"], len(ctas), affiliate_ratio)
        indexable = "noindex" not in (page.get("robots_meta") or "").lower()
        # A canonical-duplicate URL (e.g. a pagination page whose canonical
        # points elsewhere) is never an analysis target regardless of what
        # page_classifier would otherwise decide -- it isn't the canonical
        # copy of its own content (spec sections 8/12/17).
        analysis_target = is_seo_analysis_target(page_type, confidence, indexable) and not force_exclude

        self.pages.upsert(
            page["crawl_url_id"], page["crawl_run_id"], page["domain_id"], page["url"], page["normalized_url"],
            fetched_at=page["fetched_at"], page_type=page_type, page_type_confidence=confidence,
            analysis_target=1 if analysis_target else 0,
        )
        self.urls.set_analysis_target(page["crawl_url_id"], analysis_target)

        if analysis_target:
            score_and_store_page(self.db, page_id, page["crawl_run_id"], elements)

        page_keywords = self.db.query("SELECT commercial_score FROM ci_page_keywords WHERE page_id=?", (page_id,))
        avg_commercial = (
            sum(r["commercial_score"] for r in page_keywords) / len(page_keywords) if page_keywords else 0.0
        )
        has_comparison_table = any(e["element_type"] == "table" for e in elements)
        has_ranking = any(e["element_type"] == "ranking_heading" for e in elements)
        monetization_type, monetization_score = compute_monetization(
            len(ctas), affiliate_count, has_comparison_table, has_ranking, avg_commercial
        )
        self.pages.upsert(
            page["crawl_url_id"], page["crawl_run_id"], page["domain_id"], page["url"], page["normalized_url"],
            fetched_at=page["fetched_at"], monetization_type=monetization_type,
            monetization_score=monetization_score, analyzed_at=now_iso(),
        )

    def _discover_from_page(
        self, crawl_run_id: str, domain_id: str, source_url: str, parsed: ParsedPage, host: str
    ) -> int:
        # Classifies every link seen on the page, not just same-host ones --
        # an out-of-scope link (subdomain/external/asset/mailto/admin/...)
        # is still recorded, immediately excluded, per spec section 9.
        candidates = discovery_mod.discover_internal_links(source_url, parsed.all_links, host)
        new_count = 0
        for item in candidates:
            normalized = normalize_url(item["url"])
            crawl_url_id, created = self.urls.add(
                crawl_run_id, domain_id, item["url"], normalized,
                discovered_by=item.get("discovered_by", "internal_link"), source_url=item.get("source_url"),
            )
            if "exclusion_reason" in item:
                if created:
                    self.urls.mark_excluded(crawl_url_id, item["exclusion_reason"])
                continue
            if created:
                new_count += 1
        return new_count

    def _record_fetch_failure(self, crawl_url: dict, result) -> None:
        crawl_url_id = crawl_url["crawl_url_id"]
        if result.blocked and result.http_status == 403:
            self.urls.mark_excluded(crawl_url_id, ExclusionReason.CAPTCHA_BLOCKED)
            return
        if result.error == "blocked by robots.txt":
            self.urls.mark_excluded(crawl_url_id, ExclusionReason.ROBOTS_BLOCKED)
            return
        attempts = crawl_url["fetch_attempts"] + 1
        status = CrawlUrlStatus.FAILED if attempts >= MAX_FETCH_ATTEMPTS else CrawlUrlStatus.QUEUED
        self.urls.record_fetch_attempt(
            crawl_url_id, status, http_status=result.http_status, error_message=result.error
        )

    def _finalize(self, crawl_run_id: str, iterations: int) -> None:
        self.internal_links.resolve_targets(crawl_run_id)
        finalize_run(self.db, crawl_run_id)
        self.runs.update_audit(
            crawl_run_id, internal_link_phase_done=1, pagination_phase_done=1, site_aggregation_done=1,
        )
        audit = audit_mod.recompute_audit(self.db, crawl_run_id)
        converged = audit["unresolved_count"] == 0 and iterations < MAX_CONVERGENCE_ITERATIONS
        self.runs.update_audit(crawl_run_id, converged=1 if converged else 0)
        if converged:
            self.runs.set_status(crawl_run_id, CrawlRunStatus.COMPLETED)
        else:
            error = None if audit["unresolved_count"] == 0 else "convergence_iteration_guard_reached"
            self.runs.set_status(crawl_run_id, CrawlRunStatus.STOPPED, error_message=error)
