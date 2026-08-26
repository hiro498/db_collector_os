# Architecture notes

This document goes one level deeper than the README's overview. Read the
README first.

## Why one core instead of one app per DB

The project brief for this system is explicit: dozens to ~100 DB jobs are
expected over time, and a "one app per DB" design was ruled out from the
start. Concretely, that means:

- All schema lives in one SQLite database (`migrations/0001_init.sql`),
  keyed by `job_id` everywhere, not one DB file per source.
- All crawling/extraction/dedup logic lives in the core packages
  (`discovery/`, `fetching/`, `extraction/`, `normalization/`,
  `deduplication/`). Nothing in there references a specific site.
- Everything that *is* site/DB-specific is isolated behind two small,
  swappable pieces: an **Adapter** (`db_collector_os/adapters/`) and a
  **Job** row (`jobs` table, usually loaded from `config/jobs/*.yaml`).

## Module map

| Module | Responsibility |
| --- | --- |
| `config.py` | YAML + env config loading |
| `database.py` | SQLite connection, WAL/busy_timeout/foreign_keys, migration runner, integrity check |
| `models/` | Dataclasses + status/phase enums mirroring the schema |
| `job_registry.py` | Job CRUD, schedule parsing, status/phase transitions |
| `candidates.py` | `entity_candidates` store (discovery output, pre-acceptance) |
| `fetching/` | Fetch Engine (HTTP), Fetch Queue, domain rate limiter, URL normalization |
| `discovery/` | Sitemap/robots/search/prefecture/URL-pattern/internal-link/related-entity discovery methods, saturation detection, search-provider abstraction |
| `extraction/` | Common extractor (title/canonical/meta/JSON-LD/links/...) |
| `normalization/` | Whitespace/Unicode/URL/telephone/address/name normalization |
| `deduplication/` | Fingerprinting + match/merge/review decision logic |
| `entities.py` | `entities` + `evidence` (provenance) stores |
| `review/` | Review Queue store |
| `run_history.py` | Per-run counters + discovery-run stats (saturation input) |
| `metrics.py` | Daily aggregate metrics |
| `checkpoint.py` | Per-job resumable state |
| `resource_controller.py` | CPU/RAM/swap/disk/load thresholds, admission gating |
| `collectors/` | `BaseCollector` (the shared pipeline) + 4 thin per-`collector_type` subclasses + phase-transition logic |
| `adapters/` | `Adapter` base class, registry, 4 sample adapters |
| `scheduler.py` | Admits due, enabled jobs into the queue, resource-gated |
| `worker.py` | Claims queued jobs, runs the pipeline, heartbeats, stale-job recovery |
| `admin/` | FastAPI Admin UI |
| `cli.py` | `db-collector` management CLI |

## Job lifecycle (status)

```
idle --(scheduler, due)--> queued --(worker claims)--> running --+
  ^                                                               |
  |                                                    completed / retry / failed
  |                                                               |
  +---------------------------------------------------------------+
paused: excluded from `due_jobs()` entirely until resumed.
review: reserved for future use signaling a job-level (not item-level) review need.
```

A `running` job whose worker died (heartbeat/`last_started_at` older than
`worker_stale_seconds`) is reset to `retry` by
`Worker.recover_stale_jobs()`, which every worker calls periodically. It
picks up again via its persisted `fetch_queue` state and `checkpoints` row
— not from scratch.

## Phase lifecycle

```
bootstrap -> discovery -> collect -> validation -> phase1_complete -> incremental
```

See `db_collector_os/collectors/phase_manager.py`. Phase-1-completion
conditions (`queue_empty`, `min_entity_count`, `max_error_rate`,
`max_unresolved_review`, `require_discovery_saturation`,
`consecutive_low_discovery_runs`) are configurable per job via
`config_json.phase1_conditions` (falls back to sane defaults).

Discovery saturation (`discovery/saturation.py`) looks at the last N
`discovery_runs` rows: if the new-candidate rate has stayed at or below a
threshold for N consecutive runs, discovery is considered saturated for
that job, so Phase 1 doesn't crawl forever.

## Provenance

Every field written onto an `entities` row should have a matching
`evidence` row: `entity_id`, `field`, `value`, `source_url`, `fetched_at`,
`confidence`. `BaseCollector._handle_extracted` writes these together with
the entity write — see `db_collector_os/entities.py:EvidenceStore`.

## Incremental updates

Once a job reaches `incremental`, each run calls
`FetchQueue.requeue_for_revalidation(job_id, older_than_seconds)` instead of
re-crawling from scratch: previously-`done` fetch-queue rows older than the
configured interval go back to `queued`, carrying their stored `etag`/
`last_modified` forward for a conditional GET (`304 Not Modified` short-
circuits re-extraction). Sitemap `lastmod` and content-hash comparison are
the other signals available for identifying new/changed/removed items.
