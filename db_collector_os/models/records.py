"""Dataclasses mirroring the SQLite schema. Thin, mostly for type-safety and
readable construction in code; persistence lives in the *_registry / *_queue
modules, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Job:
    job_id: str
    job_name: str
    category: str
    target_db: str
    target_table: str
    collector_type: str
    adapter: str
    priority: int = 50
    enabled: bool = True
    phase: str = "bootstrap"
    schedule: str = "@hourly"
    max_pages: int = 200
    max_depth: int = 3
    concurrency: int = 2
    rate_limit: float = 1.0
    config_json: dict[str, Any] = field(default_factory=dict)
    status: str = "idle"
    created_at: str | None = None
    updated_at: str | None = None
    last_started_at: str | None = None
    last_finished_at: str | None = None
    next_run_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EntityCandidate:
    candidate_id: str
    job_id: str
    entity_type: str
    name: str | None = None
    normalized_name: str | None = None
    url: str | None = None
    source_url: str | None = None
    discovery_method: str | None = None
    fingerprint: str | None = None
    confidence: float = 0.5
    status: str = "new"
    discovered_at: str | None = None
    reviewed_at: str | None = None


@dataclass
class FetchQueueItem:
    job_id: str
    url: str
    domain: str
    priority: int = 50
    status: str = "queued"
    attempt_count: int = 0
    max_attempts: int = 5
    last_http_status: int | None = None
    next_retry_at: str | None = None
    fetched_at: str | None = None
    content_hash: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    error_message: str | None = None
    queue_id: int | None = None


@dataclass
class Entity:
    entity_id: str
    job_id: str
    entity_type: str
    name: str | None = None
    normalized_name: str | None = None
    canonical_url: str | None = None
    domain: str | None = None
    address: str | None = None
    telephone: str | None = None
    external_id: str | None = None
    fingerprint: str | None = None
    data_json: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    deleted_at: str | None = None


@dataclass
class Evidence:
    entity_id: str
    field: str
    value: str | None
    source_url: str
    fetched_at: str
    confidence: float = 0.5
    evidence_id: int | None = None


@dataclass
class ReviewItem:
    job_id: str
    reason: str
    details: str | None = None
    entity_id: str | None = None
    candidate_id: str | None = None
    status: str = "open"
    created_at: str | None = None
    resolved_at: str | None = None
    review_id: int | None = None


@dataclass
class RunHistory:
    run_id: str
    job_id: str
    started_at: str
    finished_at: str | None = None
    status: str = "running"
    discovered_count: int = 0
    fetched_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    duplicate_count: int = 0
    review_count: int = 0
    error_count: int = 0
    duration_seconds: float | None = None


@dataclass
class DiscoveryRunStats:
    job_id: str
    run_id: str
    discovered_total: int = 0
    new_candidates: int = 0
    duplicate_candidates: int = 0
    accepted: int = 0
    rejected: int = 0


@dataclass
class DailyMetrics:
    date: str
    new_entities: int = 0
    updated_entities: int = 0
    fetch_success: int = 0
    fetch_errors: int = 0
    review_count: int = 0
    jobs_executed: int = 0
    runtime_seconds: float = 0.0
    pages_fetched: int = 0


@dataclass
class Checkpoint:
    job_id: str
    run_id: str | None
    phase: str | None
    state_json: dict[str, Any] = field(default_factory=dict)
    updated_at: str | None = None
