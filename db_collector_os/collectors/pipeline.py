"""BaseCollector: the one pipeline every collector_type shares. Adapter and
Job config are the only things that differ between DBs (see 41. common
Core + Collector Type + Adapter + Job Config in the project brief).

run_once() performs one bounded unit of work (up to `max_pages` fetches) so
the Worker can call it repeatedly, checking resource/interrupt state between
calls -- this is what makes long jobs checkpoint-able and interruptible.
"""

from __future__ import annotations

import logging
from typing import Any

from ..adapters import Adapter, get_adapter
from ..adapters.base import ExtractedRecord
from ..extraction.common import extract_common
from ..fetching.urlnorm import extract_domain
from ..models.enums import CandidateStatus, JobPhase, ReviewReason
from ..normalization import normalize_address, normalize_name, normalize_telephone, normalize_url
from .context import CollectorContext
from .phase_manager import PhaseSignals, phase1_conditions_met

logger = logging.getLogger("db_collector_os.collector")


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

        run_id = state.get("current_run_id")
        if not run_id:
            run_id = ctx.run_history.start(job_id)
            state["current_run_id"] = run_id
            ctx.checkpoints.save(job_id, run_id, job["phase"], state)

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

    def _bootstrap(self, job: dict[str, Any], adapter: Adapter, state: dict[str, Any]) -> None:
        if state.get("seeded"):
            return
        for url in adapter.seed_urls(job):
            self.ctx.fetch_queue.enqueue(job["job_id"], url, priority=job.get("priority", 50))
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

        attempts = 0
        max_attempts = max_pages * 3  # allow some retries-in-loop without an infinite loop
        while outcome.fetched < max_pages and attempts < max_attempts:
            attempts += 1
            ready_domains = self._ready_domains(job_id, rate_limit)
            item = self.ctx.fetch_queue.claim_next(job_id, ready_domains=ready_domains)
            if not item:
                break
            self._process_queue_item(job, adapter, item, outcome)

    def _ready_domains(self, job_id: str, rate_limit: float) -> set[str]:
        rows = self.ctx.db.query(
            "SELECT DISTINCT domain FROM fetch_queue WHERE job_id=? AND status='queued'", (job_id,)
        )
        ready = set()
        for row in rows:
            domain = row["domain"]
            allowed, _wait = self.ctx.rate_limiter.is_allowed(domain, delay_seconds=rate_limit)
            if allowed:
                ready.add(domain)
        return ready

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

        records = self._extract_records(job, adapter, item["url"], result.content or "", result.content_type)
        ctx.fetch_queue.mark_done(queue_id, result.http_status or 200, result.content_hash, result.etag, result.last_modified)

        candidate = ctx.candidates.get_by_url(job_id, item["url"])
        for record in records:
            self._handle_extracted(job, record, item["url"], domain, candidate, outcome)

    def _extract_records(
        self, job: dict[str, Any], adapter: Adapter, url: str, content: str, content_type: str | None
    ) -> list[ExtractedRecord]:
        """Default (HTML collectors): one page -> one record. Overridden by
        ApiCollector, where one JSON response can list many entities.
        """
        common = extract_common(content, url)
        self.ctx.discovery.discover_from_page(job, common, extract_domain(url))
        return [adapter.extract(common, url, content)]

    def _handle_extracted(
        self, job: dict[str, Any], record: ExtractedRecord, source_url: str, domain: str,
        candidate: dict[str, Any] | None, outcome: RunOutcome,
    ) -> None:
        ctx = self.ctx
        job_id = job["job_id"]

        if record.missing_required:
            ctx.review.add(
                job_id, ReviewReason.MISSING_REQUIRED_FIELD,
                details=f"missing: {record.missing_required}", candidate_id=candidate["candidate_id"] if candidate else None,
            )
            if candidate:
                ctx.candidates.set_status(candidate["candidate_id"], CandidateStatus.REVIEW)
            outcome.reviewed += 1
            return

        normalized_name = normalize_name(record.name)
        address = normalize_address(record.address) if record.address else None
        telephone = normalize_telephone(record.telephone) if record.telephone else None
        canonical_url = normalize_url(record.canonical_url or source_url)

        decision = ctx.dedup.resolve(
            job_id, record.entity_type or job["collector_type"], name=record.name,
            normalized_name=normalized_name, canonical_url=canonical_url, domain=domain,
            address=address, telephone=telephone, external_id=record.external_id,
        )

        if decision.action == "new":
            entity_id = ctx.entities.create(
                job_id=job_id, entity_type=record.entity_type or job["collector_type"], name=record.name,
                normalized_name=normalized_name, canonical_url=canonical_url, domain=domain,
                address=address, telephone=telephone, external_id=record.external_id,
                fingerprint=decision.fingerprint, data=record.fields,
            )
            ctx.evidence.record_many(entity_id, {**record.fields, "name": record.name}, source_url, record.confidence)
            outcome.inserted += 1
            if candidate:
                ctx.candidates.set_status(candidate["candidate_id"], CandidateStatus.ACCEPTED)
        elif decision.action == "merge":
            ctx.entities.merge_data(decision.entity_id, record.fields)
            ctx.evidence.record_many(decision.entity_id, {**record.fields, "name": record.name}, source_url, record.confidence)
            outcome.updated += 1
            outcome.duplicates += 1
            if candidate:
                ctx.candidates.set_status(candidate["candidate_id"], CandidateStatus.DUPLICATE)
        else:  # review
            ctx.review.add(
                job_id, ReviewReason.DUPLICATE_AMBIGUITY, details=decision.reason,
                entity_id=decision.entity_id, candidate_id=candidate["candidate_id"] if candidate else None,
            )
            if candidate:
                ctx.candidates.set_status(candidate["candidate_id"], CandidateStatus.REVIEW)
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
