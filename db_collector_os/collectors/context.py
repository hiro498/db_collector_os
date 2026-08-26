"""CollectorContext bundles every store/engine a collector run needs, so the
pipeline and the worker don't have to pass a dozen positional arguments
around.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..candidates import CandidateStore
from ..checkpoint import CheckpointStore
from ..config import AppConfig
from ..database import Database
from ..deduplication import Deduplicator
from ..discovery import DiscoveryEngine
from ..entities import EntityStore, EvidenceStore
from ..fetching import DomainRateLimiter, FetchEngine, FetchQueue
from ..job_registry import JobRegistry
from ..metrics import MetricsStore
from ..review import ReviewQueue
from ..run_history import RunHistoryStore


@dataclass
class CollectorContext:
    config: AppConfig
    db: Database
    jobs: JobRegistry
    candidates: CandidateStore
    fetch_queue: FetchQueue
    rate_limiter: DomainRateLimiter
    fetch_engine: FetchEngine
    discovery: DiscoveryEngine
    entities: EntityStore
    evidence: EvidenceStore
    dedup: Deduplicator
    review: ReviewQueue
    run_history: RunHistoryStore
    checkpoints: CheckpointStore
    metrics: MetricsStore

    @classmethod
    def build(cls, config: AppConfig, db: Database, search_provider=None) -> "CollectorContext":
        from ..discovery.search_provider import build_search_provider

        fetch_engine = FetchEngine(user_agent=config.user_agent)
        candidates = CandidateStore(db)
        entities = EntityStore(db)
        provider = search_provider or build_search_provider(config.search_provider, config.search_api_key)
        return cls(
            config=config,
            db=db,
            jobs=JobRegistry(db),
            candidates=candidates,
            fetch_queue=FetchQueue(db),
            rate_limiter=DomainRateLimiter(db),
            fetch_engine=fetch_engine,
            discovery=DiscoveryEngine(fetch_engine, candidates, provider),
            entities=entities,
            evidence=EvidenceStore(db),
            dedup=Deduplicator(entities),
            review=ReviewQueue(db),
            run_history=RunHistoryStore(db),
            checkpoints=CheckpointStore(db),
            metrics=MetricsStore(db),
        )
