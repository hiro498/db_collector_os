"""BaseCollector: the one pipeline every collector_type shares. Adapter and
Job config are the only things that differ between DBs (see 41. common
Core + Collector Type + Adapter + Job Config in the project brief).

run_once() performs one bounded unit of work (up to `max_pages` fetches) so
the Worker can call it repeatedly, checking resource/interrupt state between
calls -- this is what makes long jobs checkpoint-able and interruptible.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..adapters import Adapter, get_adapter
from ..adapters.base import ExtractedRecord
from ..extraction.common import extract_common
from ..fetching.urlnorm import extract_domain
from ..models.enums import CandidateStatus, JobPhase, ReviewReason, RunStatus
from ..normalization import normalize_address, normalize_name, normalize_telephone, normalize_url
from ..persistence import PersistenceService
from .context import CollectorContext
from .phase_manager import PhaseSignals, phase1_conditions_met

logger = logging.getLogger("db_collector_os.collector")


def ensure_seed_urls_queued(
    ctx: CollectorContext, job: dict[str, Any], adapter: Adapter | None = None
) -> list[str]:
    """Idempotently enqueue every URL the job's CURRENT config_json.seed_urls
    names into fetch_queue. Safe to call from any process, any number of
    times: `FetchQueue.enqueue()` is idempotent per `(job_id, normalized
    url)` -- a URL already tracked in fetch_queue (any status, including
    'done') is left completely untouched, never duplicated and never forced
    to re-fetch. Returns the URLs that were newly added this call (for
    logging/reporting; an empty list is not an error -- it just means
    nothing was new).

    This is a standalone function, not just a `BaseCollector` method, so it
    can also be invoked directly and synchronously by a short-lived CLI
    process (see `db-collector jobs reseed`) -- guaranteeing a config-added
    seed reaches the queue immediately from code that is *always* current
    (a fresh process reads whatever is on disk right now), rather than only
    ever depending on the long-running worker process's next `run_once()`
    tick, which serves whatever code it happened to have loaded at its own
    last start. `BaseCollector.run_once()` still also calls this on every
    tick as its own, independent guarantee (belt-and-suspenders) -- calling
    it twice for the same URL from two different processes is harmless.
    """
    adapter = adapter or get_adapter(job["adapter"])
    job_id = job["job_id"]
    newly_queued: list[str] = []
    for url in adapter.seed_urls(job):
        normalized = normalize_url(url)
        if not normalized:
            continue
        already_tracked = ctx.fetch_queue.exists(job_id, normalized)
        ctx.fetch_queue.enqueue(job_id, url, priority=job.get("priority", 50))
        if not already_tracked:
            newly_queued.append(normalized)
    return newly_queued


class RunOutcome:
    def __init__(self):
        self.fetched = 0
        self.inserted = 0
        self.updated = 0
        self.duplicates = 0
        self.reviewed = 0
        self.errors = 0
        self.discovered = 0

    def as_kwargs(self) -> dict[str, int]:
        return {
            "fetched_count": self.fetched,
            "inserted_count": self.inserted,
            "updated_count": self.updated,
            "duplicate_count": self.duplicates,
            "review_count": self.reviewed,
            "error_count": self.errors,
            "discovered_count": self.discovered,
        }


class BaseCollector:
    """Generic pipeline. Subclasses may override `fetch_and_extract` for
    collector types whose transport differs (e.g. `api`, which speaks JSON
    instead of crawling HTML).
    """

    def __init__(self, ctx: CollectorContext):
        self.ctx = ctx

    def run_once(self, job: dict[str, Any]) -> RunOutcome:
        ctx = self.ctx
        job_id = job["job_id"]
        adapter = get_adapter(job["adapter"])
        outcome = RunOutcome()

        ctx.fetch_queue.requeue_stale_fetching(job_id)
        checkpoint = ctx.checkpoints.load(job_id)
        state = checkpoint["state"]

        # current_run_id in checkpoint state is ONLY a crash-resume marker:
        # if the worker died inside run_once() before run_job_and_record()
        # could finalize it, the run_history row is still status='running'
        # and it's correct to continue writing into that same row. Any other
        # value here (stale/corrupted state, e.g. left over from before this
        # resume mechanism existed) must never be reused -- run_history is
        # immutable execution history, so a new execution always gets a new
        # run_id unless it is genuinely resuming an unfinished one.
        run_id = state.get("current_run_id")
        existing_run = ctx.run_history.get(run_id) if run_id else None
        if not existing_run or existing_run["status"] != RunStatus.RUNNING:
            run_id = ctx.run_history.start(job_id)
            state["current_run_id"] = run_id
            ctx.checkpoints.save(job_id, run_id, job["phase"], state)

        # Idempotent seed upsert: derived from the job's CURRENT config on
        # every execution, not gated behind the one-time "seeded" bootstrap
        # flag below. A job config that grows new seed_urls after the
        # bootstrap phase already completed (e.g. adding a listing-page
        # seed on top of a single already-fetched product URL) gets the
        # new seed queued on the very next run instead of being silently
        # skipped forever. fetch_queue.enqueue() already no-ops for a URL
        # already tracked (any status, including 'done'), so this never
        # duplicates rows and never forces an already-fetched seed to
        # re-fetch -- that stays owned by requeue_for_revalidation().
        self._ensure_seed_urls_queued(job, adapter)

        if job["phase"] == JobPhase.BOOTSTRAP:
            self._bootstrap(job, adapter, state)
            ctx.jobs.set_phase(job_id, JobPhase.DISCOVERY)
            job = {**job, "phase": JobPhase.DISCOVERY}

        if job["phase"] in (JobPhase.DISCOVERY, JobPhase.COLLECT):
            found = ctx.discovery.run_seed_discovery(job)
            outcome.discovered += len(found)
        elif job["phase"] == JobPhase.INCREMENTAL:
            revalidate_after = (job.get("config_json", {}) or {}).get("incremental_revalidate_after_seconds", 86400)
            ctx.fetch_queue.requeue_for_revalidation(job_id, revalidate_after)
            found = ctx.discovery.run_seed_discovery(job)
            outcome.discovered += len(found)

        self._promote_new_candidates(job, outcome)
        self._drain_fetch_queue(job, adapter, outcome)

        ctx.run_history.record_discovery_stats(
            job_id, run_id,
            discovered_total=ctx.candidates.total_count(job_id),
            new_candidates=outcome.discovered,
            duplicate_candidates=ctx.candidates.counts_by_status(job_id).get(CandidateStatus.DUPLICATE, 0),
            accepted=ctx.candidates.counts_by_status(job_id).get(CandidateStatus.ACCEPTED, 0),
            rejected=ctx.candidates.counts_by_status(job_id).get(CandidateStatus.REJECTED, 0),
        )

        new_phase = self._advance_phase(job, state)

        ctx.checkpoints.save(job_id, run_id, new_phase, state)
        ctx.metrics.bump(
            fetch_success=outcome.fetched - outcome.errors if outcome.fetched >= outcome.errors else 0,
            fetch_errors=outcome.errors,
            review_count=outcome.reviewed,
            pages_fetched=outcome.fetched,
            new_entities=outcome.inserted,
            updated_entities=outcome.updated,
            jobs_executed=1,
        )
        return outcome

    # -- pipeline steps -----------------------------------------------

    def _ensure_seed_urls_queued(self, job: dict[str, Any], adapter: Adapter) -> None:
        ensure_seed_urls_queued(self.ctx, job, adapter)

    def _bootstrap(self, job: dict[str, Any], adapter: Adapter, state: dict[str, Any]) -> None:
        if state.get("seeded"):
            return
        self.ctx.discovery.run_seed_discovery(job)
        state["seeded"] = True

    def _promote_new_candidates(self, job: dict[str, Any], outcome: RunOutcome, limit: int = 500) -> None:
        job_id = job["job_id"]
        for candidate in self.ctx.candidates.list_new(job_id, limit=limit):
            priority = int(50 + candidate.get("confidence", 0.5) * 50)
            self.ctx.fetch_queue.enqueue(job_id, candidate["url"], priority=priority)

    def _drain_fetch_queue(self, job: dict[str, Any], adapter: Adapter, outcome: RunOutcome) -> None:
        job_id = job["job_id"]
        max_pages = job.get("max_pages", 200)
        rate_limit = job.get("rate_limit", 1.0)
        # Opt-in only (default 0): how long this ONE run_once() call may
        # spend sleeping through per-domain rate-limit waits so it can keep
        # draining the queue toward max_pages, instead of giving up the
        # instant the (usually single) domain involved isn't immediately
        # ready. Without this, a job whose queue holds many same-domain
        # URLs -- exactly the Good Smile Phase 1 case -- fetches exactly
        # one page per run_once() call every time rate_limit > 0, turning
        # "one batch, up to max_pages" into "max_pages separate runs".
        # Defaults to 0 (today's behavior: give up immediately, defer the
        # rest to a later run) so every job that doesn't opt in -- and
        # every existing test -- is completely unaffected.
        max_drain_wait = (job.get("config_json", {}) or {}).get("max_drain_wait_seconds", 0) or 0

        attempts = 0
        max_attempts = max_pages * 3  # allow some retries-in-loop without an infinite loop
        waited_total = 0.0
        while outcome.fetched < max_pages and attempts < max_attempts:
            attempts += 1
            ready_domains, min_wait = self._ready_domains(job_id, rate_limit)
            item = self.ctx.fetch_queue.claim_next(job_id, ready_domains=ready_domains) if ready_domains else None
            if item:
                self._process_queue_item(job, adapter, item, outcome)
                continue
            if min_wait is None:
                break  # nothing queued at all -- genuinely empty, not rate-limited
            if max_drain_wait > 0 and waited_total + min_wait <= max_drain_wait:
                time.sleep(min_wait)
                waited_total += min_wait
                continue
            break  # would exceed this run's drain-wait budget -- defer the rest to a later run

    def _ready_domains(self, job_id: str, rate_limit: float) -> tuple[set[str], float | None]:
        """Returns (domains ready to fetch now, seconds until the soonest
        currently-queued domain becomes ready -- None if nothing is queued
        at all)."""
        rows = self.ctx.db.query(
            "SELECT DISTINCT domain FROM fetch_queue WHERE job_id=? AND status='queued'", (job_id,)
        )
        ready = set()
        min_wait: float | None = None
        for row in rows:
            domain = row["domain"]
            allowed, wait = self.ctx.rate_limiter.is_allowed(domain, delay_seconds=rate_limit)
            if allowed:
                ready.add(domain)
            elif min_wait is None or wait < min_wait:
                min_wait = wait
        return ready, min_wait

    def _process_queue_item(self, job: dict[str, Any], adapter: Adapter, item: dict[str, Any], outcome: RunOutcome) -> None:
        ctx = self.ctx
        job_id = job["job_id"]
        queue_id = item["queue_id"]
        domain = item["domain"]

        ctx.rate_limiter.record_request(domain)
        result = ctx.fetch_engine.fetch(item["url"], etag=item.get("etag"), last_modified=item.get("last_modified"))
        outcome.fetched += 1

        if result.blocked:
            ctx.rate_limiter.record_error(domain)
            ctx.fetch_queue.mark_skipped(queue_id, result.error or "blocked")
            candidate = ctx.candidates.get_by_url(job_id, item["url"])
            ctx.review.add(
                job_id, ReviewReason.CAPTCHA if "captcha" in (result.error or "") else ReviewReason.BLOCKED,
                details=result.error, candidate_id=candidate["candidate_id"] if candidate else None,
            )
            outcome.reviewed += 1
            outcome.errors += 1
            return

        if not result.ok:
            ctx.rate_limiter.record_error(domain, block_seconds=result.retry_after)
            ctx.fetch_queue.mark_failed(queue_id, result.error or "unknown error", result.http_status, result.retry_after)
            outcome.errors += 1
            row = ctx.db.query_one("SELECT status FROM fetch_queue WHERE queue_id=?", (queue_id,))
            if row and row["status"] == "failed":
                candidate = ctx.candidates.get_by_url(job_id, item["url"])
                ctx.review.add(
                    job_id, ReviewReason.PARSE_FAILURE, details=f"fetch failed permanently: {result.error}",
                    candidate_id=candidate["candidate_id"] if candidate else None,
                )
                outcome.reviewed += 1
            return

        ctx.rate_limiter.record_success(domain)

        if result.http_status == 304:
            ctx.fetch_queue.mark_done(queue_id, 304, content_hash=item.get("content_hash"), etag=item.get("etag"), last_modified=item.get("last_modified"))
            return

        records = self._extract_records(job, adapter, item["url"], result.content or "", result.content_type, outcome)
        ctx.fetch_queue.mark_done(queue_id, result.http_status or 200, result.content_hash, result.etag, result.last_modified)

        candidate = ctx.candidates.get_by_url(job_id, item["url"])
        for record in records:
            self._handle_extracted(job, record, item["url"], domain, candidate, outcome)

    def _extract_records(
        self, job: dict[str, Any], adapter: Adapter, url: str, content: str, content_type: str | None,
        outcome: RunOutcome,
    ) -> list[ExtractedRecord]:
        """Default (HTML collectors): one page -> one record. Overridden by
        ApiCollector, where one JSON response can list many entities.

        A page processed here during `_drain_fetch_queue()` (e.g. the
        scalefigure_list listing page) may itself discover new product-page
        candidates via `discover_from_page()`. Those must (a) correctly
        count toward `outcome.discovered` -- `discover_from_page()` already
        returns only genuinely-new candidates, see DiscoveryEngine.
        _save_candidates -- and (b) become fetchable within this SAME
        bounded run rather than waiting for a follow-up run_once() call, so
        promote them into fetch_queue immediately via the same idempotent
        `_promote_new_candidates()` the top of run_once() already uses (its
        `CandidateStore.list_new()` + `FetchQueue.enqueue()` are both safe
        to call repeatedly within one run -- enqueue() no-ops for a URL
        already tracked, and a candidate stays selectable by list_new()
        only until it is actually fetched and its status changes off
        'new'). `_drain_fetch_queue()`'s own `outcome.fetched < max_pages`
        loop condition is untouched, so this can add queue depth but can
        never cause more than max_pages fetches in this run.
        """
        common = extract_common(content, url)
        newly_discovered = self.ctx.discovery.discover_from_page(job, common, extract_domain(url))
        if newly_discovered:
            outcome.discovered += len(newly_discovered)
            self._promote_new_candidates(job, outcome)
        return [adapter.extract(common, url, content)]

    def _handle_extracted(
        self, job: dict[str, Any], record: ExtractedRecord, source_url: str, domain: str,
        candidate: dict[str, Any] | None, outcome: RunOutcome,
    ) -> None:
        ctx = self.ctx
        job_id = job["job_id"]

        persistence = PersistenceService(
            entities=ctx.entities,
            evidence=ctx.evidence,
            dedup=ctx.dedup,
        )

        result = persistence.persist(
            job_id=job_id,
            record=record,
            source_url=source_url,
            domain=domain,
            default_entity_type=job["collector_type"],
        )

        if result.action == "skip":
            if candidate:
                ctx.candidates.set_status(
                    candidate["candidate_id"],
                    CandidateStatus.REJECTED,
                )
            return

        if result.action == "invalid":
            missing = [
                error.split(":", 1)[1]
                for error in result.errors
                if error.startswith("missing_required:")
            ]

            reason = (
                ReviewReason.MISSING_REQUIRED_FIELD
                if missing
                else ReviewReason.PARSE_FAILURE
            )

            details = (
                f"missing: {missing}"
                if missing
                else "record validation failed: " + "; ".join(result.errors)
            )

            ctx.review.add(
                job_id,
                reason,
                details=details,
                candidate_id=(
                    candidate["candidate_id"]
                    if candidate
                    else None
                ),
            )

            if candidate:
                ctx.candidates.set_status(
                    candidate["candidate_id"],
                    CandidateStatus.REVIEW,
                )

            outcome.reviewed += 1
            return

        if result.action == "inserted":
            outcome.inserted += 1

            if candidate:
                ctx.candidates.set_status(
                    candidate["candidate_id"],
                    CandidateStatus.ACCEPTED,
                )

            return

        if result.action == "updated":
            outcome.updated += 1
            outcome.duplicates += 1

            if candidate:
                ctx.candidates.set_status(
                    candidate["candidate_id"],
                    CandidateStatus.DUPLICATE,
                )

            return

        if result.action == "review":
            ctx.review.add(
                job_id,
                ReviewReason.DUPLICATE_AMBIGUITY,
                details=result.reason,
                entity_id=result.entity_id,
                candidate_id=(
                    candidate["candidate_id"]
                    if candidate
                    else None
                ),
            )

            if candidate:
                ctx.candidates.set_status(
                    candidate["candidate_id"],
                    CandidateStatus.REVIEW,
                )

            outcome.reviewed += 1
            return

        ctx.review.add(
            job_id,
            ReviewReason.PARSE_FAILURE,
            details=f"unknown persistence action: {result.action}",
            candidate_id=(
                candidate["candidate_id"]
                if candidate
                else None
            ),
        )

        if candidate:
            ctx.candidates.set_status(
                candidate["candidate_id"],
                CandidateStatus.REVIEW,
            )

        outcome.reviewed += 1

    def _advance_phase(self, job: dict[str, Any], state: dict[str, Any]) -> str:
        from ..discovery.saturation import SaturationConfig, is_saturated

        ctx = self.ctx
        job_id = job["job_id"]
        phase = job["phase"]

        if phase == JobPhase.INCREMENTAL:
            return phase  # steady state; no further auto-transition

        queue_empty = ctx.fetch_queue.is_empty(job_id)
        saturated, _reason = is_saturated(ctx.run_history, job_id, SaturationConfig())

        low_run_streak = state.get("low_discovery_streak", 0)
        recent = ctx.run_history.recent_discovery_runs(job_id, n=1)
        if recent:
            total = recent[0]["discovered_total"] or 0
            new = recent[0]["new_candidates"] or 0
            rate = (new / total) if total else 0.0
            low_run_streak = low_run_streak + 1 if rate <= 0.05 else 0
        state["low_discovery_streak"] = low_run_streak

        stats = ctx.run_history.for_job(job_id, limit=1)
        error_rate = 0.0
        if stats:
            fetched = stats[0].get("fetched_count") or 0
            errors = stats[0].get("error_count") or 0
            error_rate = (errors / fetched) if fetched else 0.0

        signals = PhaseSignals(
            queue_empty=queue_empty,
            entity_count=ctx.entities.count(job_id),
            error_rate=error_rate,
            unresolved_review_count=ctx.review.count_open(job_id),
            discovery_saturated=saturated,
            consecutive_low_discovery_runs=low_run_streak,
        )

        if phase in (JobPhase.DISCOVERY, JobPhase.COLLECT):
            if queue_empty and saturated:
                new_phase = JobPhase.VALIDATION if phase == JobPhase.COLLECT else JobPhase.COLLECT
            elif not queue_empty:
                new_phase = JobPhase.COLLECT
            else:
                new_phase = phase
        elif phase == JobPhase.VALIDATION:
            conditions = (job.get("config_json", {}) or {}).get("phase1_conditions")
            met, _unmet = phase1_conditions_met(signals, conditions)
            new_phase = JobPhase.PHASE1_COMPLETE if met else JobPhase.VALIDATION
        elif phase == JobPhase.PHASE1_COMPLETE:
            new_phase = JobPhase.INCREMENTAL
        else:
            new_phase = phase

        if new_phase != phase:
            ctx.jobs.set_phase(job_id, new_phase)
        return new_phase
