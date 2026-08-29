"""Discovery Engine: orchestrates every discovery method for a job and lands
results as `entity_candidate` rows (never straight into `entities`).

Two entry points:
  * run_seed_discovery -- sitemap / robots.txt / search / prefecture / URL
    pattern methods, driven entirely by job config. This is what Phase
    "discovery" repeatedly calls.
  * discover_from_page -- internal-link / related-entity discovery, run
    against a page that was already fetched during the "collect" phase, so
    the crawl keeps growing outward from confirmed pages too.

A failure in any single method (e.g. the search provider is unset, or one
sitemap 404s) never aborts the others -- each method is wrapped so the engine
always returns whatever it could gather.
"""

from __future__ import annotations

import logging
from typing import Any

from ..candidates import CandidateStore
from ..fetching.client import FetchEngine
from ..normalization import normalize_url
from .base import DiscoveredURL
from .internal_links import discover_internal_links
from .prefecture import discover_by_prefecture
from .related_entity import discover_related_entities
from .robots_sitemap import discover_from_robots
from .search_discovery import discover_from_search
from .search_provider import SearchProvider
from .sitemap import discover_from_sitemap
from .url_pattern import discover_by_url_pattern

logger = logging.getLogger("db_collector_os.discovery")


class DiscoveryEngine:
    def __init__(
        self,
        fetch_engine: FetchEngine,
        candidates: CandidateStore,
        search_provider: SearchProvider,
    ):
        self.fetch_engine = fetch_engine
        self.candidates = candidates
        self.search_provider = search_provider

    def run_seed_discovery(self, job: dict[str, Any]) -> list[DiscoveredURL]:
        """Returns only the DiscoveredURLs that became genuinely new
        `entity_candidates` rows this call (see `_save_candidates`) -- not
        every URL observed, which routinely includes items already known
        from a prior run/page."""
        cfg = job.get("config_json", {}) or {}
        discovery_cfg = cfg.get("discovery", {}) or {}
        found: list[DiscoveredURL] = []

        for sitemap_url in discovery_cfg.get("sitemap_urls", []):
            found.extend(self._safe(discover_from_sitemap, self.fetch_engine, sitemap_url))

        for seed_url in discovery_cfg.get("robots_seed_urls", []):
            found.extend(self._safe(discover_from_robots, self.fetch_engine, seed_url))

        queries = discovery_cfg.get("search_queries", [])
        if queries:
            found.extend(self._safe(discover_from_search, self.search_provider, queries))

        pref_template = discovery_cfg.get("prefecture_url_template")
        if pref_template:
            found.extend(
                self._safe(discover_by_prefecture, pref_template, discovery_cfg.get("prefecture_use_slug", False))
            )

        pattern_cfg = discovery_cfg.get("url_pattern")
        if pattern_cfg:
            found.extend(
                self._safe(
                    discover_by_url_pattern,
                    pattern_cfg["template"], pattern_cfg["start"], pattern_cfg["end"],
                    pattern_cfg.get("step", 1), pattern_cfg.get("placeholder", "{n}"),
                )
            )

        return self._save_candidates(job, found)

    def discover_from_page(self, job: dict[str, Any], extracted: dict[str, Any], page_domain: str) -> list[DiscoveredURL]:
        """Same "genuinely new only" return semantics as `run_seed_discovery`
        (see `_save_candidates`) -- callers rely on `len(...)` of this to
        mean actual new candidates attributable to processing this one page,
        not every link observed on it."""
        cfg = job.get("config_json", {}) or {}
        discovery_cfg = cfg.get("discovery", {}) or {}
        found: list[DiscoveredURL] = []

        if discovery_cfg.get("internal_links", True):
            allowed = set(discovery_cfg.get("allowed_domains", [])) or {page_domain}
            url_pattern = discovery_cfg.get("product_url_pattern")
            found.extend(
                self._safe(discover_internal_links, extracted.get("links", []), page_domain, allowed, url_pattern)
            )

        if discovery_cfg.get("related_entities", True):
            found.extend(self._safe(discover_related_entities, extracted.get("json_ld", [])))

        return self._save_candidates(job, found)

    def _safe(self, fn, *args, **kwargs) -> list[DiscoveredURL]:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # a single method failing must never halt discovery
            logger.warning("discovery method %s failed: %s", getattr(fn, "__name__", fn), exc)
            return []

    def _save_candidates(self, job: dict[str, Any], found: list[DiscoveredURL]) -> list[DiscoveredURL]:
        """Persist every item in `found` (via the idempotent, fingerprint-
        deduped `CandidateStore.add()`) and return only the subset that was
        genuinely a NEW candidate row this call -- not `found` itself.

        `found` is whatever a discovery method observed on this pass, which
        routinely re-observes URLs already known from a previous page/run
        (e.g. a repeated nav link). Returning `found` verbatim would make
        every caller's `len(...)` count re-observed duplicates as if they
        were newly discovered, which is exactly the
        run_history.discovered_count / discovery_runs.new_candidates
        semantics this must not produce (see RunOutcome.discovered in
        collectors/pipeline.py). `CandidateStore.add()` already reports
        `(candidate_id, created)`; this just stops discarding that.
        """
        entity_type = job.get("category") or job.get("collector_type", "entity")
        newly_created: list[DiscoveredURL] = []
        for item in found:
            url = normalize_url(item.url)
            if not url:
                continue
            # A stable_id (e.g. a numeric product ID captured from the URL)
            # fingerprints candidates by real-world identity rather than by
            # URL, so two different URLs for the same product (different
            # slug, tracking params, ...) collapse into one candidate before
            # either is ever fetched -- see discovery/internal_links.py.
            fingerprint = f"{entity_type}:{item.stable_id}" if item.stable_id else url
            _candidate_id, created = self.candidates.add(
                job_id=job["job_id"],
                entity_type=entity_type,
                name=None,
                normalized_name=None,
                url=url,
                source_url=url,
                discovery_method=item.method,
                fingerprint=fingerprint,
                confidence=item.confidence,
            )
            if created:
                newly_created.append(item)
        return newly_created
