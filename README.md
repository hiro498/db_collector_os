# DB Collector OS

**DB Collector OS** is a common, unattended platform for discovering,
collecting, updating, and diff-monitoring many different kinds of databases
from a single VPS — without a human (or an LLM chat session) driving each
run.

It is **not** a single-purpose crawler. It is a small "operating system" for
data collection: one core (Job Registry, Scheduler, Worker, Discovery
Engine, Fetch Engine, Extractor, Normalizer, Deduplicator, DB Writer, Review
Queue, Checkpoint/Resume, Metrics, Resource Controller, Admin UI) shared by
every DB you register, plus a small **Adapter** and **Job definition** per
DB. Adding DB #47 should never require touching the core.

```
Claude Code  ->  GitHub repository  ->  VPS: git pull  ->  install/update  ->  systemd  ->  autonomous collection
```

Claude Code never runs on the VPS. All development happens against this
repository; the VPS only pulls, installs, and runs.

## Table of contents

- [Architecture](#architecture)
- [Local development](#local-development)
- [VPS deployment](#vps-deployment)
  - [First install](#first-install)
  - [Update](#update)
  - [Rollback](#rollback)
- [Add a new DB](#add-a-new-db)
- [Add a new Adapter](#add-a-new-adapter)
- [Add a new Job](#add-a-new-job)
- [Admin UI](#admin-ui)
- [CLI](#cli)
- [systemd](#systemd)
- [Backup](#backup)
- [Troubleshooting](#troubleshooting)

## Architecture

```
DB Collector OS
│
├── Source Registry (config/jobs/*.yaml -> `jobs` table)
├── Job Registry           (db_collector_os/job_registry.py)
├── Scheduler               (db_collector_os/scheduler.py)
├── Fetch Queue / Job Queue (db_collector_os/fetching/queue.py, `jobs.status`)
├── Worker                  (db_collector_os/worker.py)
├── Discovery Engine         (db_collector_os/discovery/)
├── Fetch Engine             (db_collector_os/fetching/)
├── Extractor                (db_collector_os/extraction/)
├── Normalizer                (db_collector_os/normalization/)
├── Deduplicator               (db_collector_os/deduplication/)
├── DB Writer                  (db_collector_os/entities.py + evidence)
├── Incremental Update Engine  (ETag/Last-Modified/content_hash, see fetching/queue.py)
├── Review Queue                (db_collector_os/review/)
├── Retry / Error Handler        (fetching/queue.py backoff, review routing)
├── Resource Controller           (db_collector_os/resource_controller.py)
├── Metrics                        (db_collector_os/metrics.py)
├── Checkpoint / Resume             (db_collector_os/checkpoint.py)
└── Admin UI                         (db_collector_os/admin/, FastAPI)
```

**Collector Types** (`collector_type` on a Job) are the four supported
transport/extraction shapes: `official_site`, `local_business`, `person`,
`api`. Each has a thin collector class in `db_collector_os/collectors/`, but
almost all DB-specific behavior lives in an **Adapter**
(`db_collector_os/adapters/`). A new DB = one Adapter + one Job YAML file —
the pipeline in `db_collector_os/collectors/pipeline.py` (`BaseCollector`)
is shared by everything.

**Pipeline per job run** (`BaseCollector.run_once`, called by the Worker):

1. Recover any fetch-queue rows stuck `fetching` from a killed process.
2. `bootstrap`: enqueue `Adapter.seed_urls()`, run one round of Discovery.
3. `discovery`/`collect`: run Discovery methods (sitemap, robots.txt
   sitemap, search-query, prefecture, URL-pattern; internal-link and
   related-entity discovery run per fetched page), promote new
   `entity_candidates` into the Fetch Queue, drain the Fetch Queue up to
   `max_pages` fetches (respecting per-domain rate limits), extract with
   the common extractor + Adapter, normalize, deduplicate, write
   entities/evidence or route to the Review Queue.
4. `validation`: check the job's Phase-1-completion conditions.
5. `phase1_complete` -> `incremental`: steady state. Each run periodically
   re-enqueues previously-fetched pages for conditional re-fetch
   (`ETag`/`If-Modified-Since`) instead of re-crawling everything.

Phase transitions, run counters, checkpoints, and discovery-saturation
stats are all persisted to SQLite after every run, so a VPS reboot or a
killed worker process resumes from where it left off (see
[Checkpoint / Resume](#troubleshooting)).

### Data model (SQLite)

`jobs`, `entity_candidates`, `fetch_queue`, `domain_rate_limits`,
`entities`, `evidence` (provenance: which URL, when, what confidence, for
every field), `review_queue`, `run_history`, `discovery_runs`,
`daily_metrics`, `checkpoints`, `workers`, `schema_migrations`. Full schema:
`migrations/0001_init.sql`.

## Local development

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # adjust as needed; .env is git-ignored

db-collector migrate           # create/upgrade the SQLite schema
db-collector jobs sync          # load config/jobs/*.yaml into the registry
db-collector jobs list

pytest                           # full test suite (all network calls are mocked)
```

Run the pieces manually while developing:

```bash
db-collector scheduler run --once   # queue any due, enabled jobs once
db-collector worker run --once      # process at most one queued job, once
db-collector admin serve            # http://127.0.0.1:8787
```

## VPS deployment

Production layout on the VPS is fixed at:

```
/root/tools/db_collector_os
```

Claude Code never runs on the VPS — the VPS only runs `git pull` against
this repository plus the scripts in `scripts/`.

### First install

On the VPS, as root:

See the copy-pasteable command block at the very end of this README. It is
safe to run whether `/root/tools/db_collector_os` doesn't exist yet, exists
as an empty/uninitialized git repo, or already has `origin` configured: it
never force-pushes, never discards local commits, and refuses to touch the
directory (no deletion) if it exists but isn't a git repository at all.
`install_vps.sh` itself never deletes an existing `.env` or existing SQLite
data.

`install_vps.sh` performs, in order: OS precheck, Python version check,
venv creation, dependency install, runtime directory creation, `.env`
bootstrap (from `.env.example`, only if missing), DB migration, job sync
(`config/jobs/*.yaml`), permission tightening, systemd unit install,
`daemon-reload`, `enable --now` for the scheduler/worker/admin services,
healthcheck, and a DB integrity check. It is idempotent — safe to re-run.

By default the shipped sample jobs (`config/jobs/*.yaml`) are
`enabled: false` so nothing crawls the internet until you edit a job's
`seed_urls` and flip it on (`db-collector jobs resume <job_id>` or edit the
YAML and re-run `db-collector jobs sync`).

### Update

```bash
cd /root/tools/db_collector_os
./scripts/update_vps.sh
```

Performs, in order: record the current commit, back up the DB + config
(`scripts/backup.sh`), `git fetch` + fast-forward-only merge (refuses to
run if the working tree has uncommitted changes, or if the merge isn't a
fast-forward), dependency update, migration, service restart, healthcheck,
integrity check.

### Rollback

`update_vps.sh` never force-pushes or rewrites history. If a healthcheck or
integrity check fails after an update, the script **stops** (it does not
silently continue) and prints the exact rollback commands, e.g.:

```bash
cd /root/tools/db_collector_os
git checkout <previous-commit-sha>     # printed by update_vps.sh
.venv/bin/pip install -e .
.venv/bin/db-collector migrate
systemctl restart db-collector-scheduler db-collector-worker@1 db-collector-admin
```

Set `AUTO_ROLLBACK=1 ./scripts/update_vps.sh` to have the script attempt
this automatically on failure instead of just printing it.

A timestamped pre-update DB + config backup is always taken first (under
`var/backups/<timestamp>/`) — restore it with:

```bash
systemctl stop db-collector-scheduler 'db-collector-worker@*' db-collector-admin
cp var/backups/<timestamp>/db_collector.sqlite3 var/db_collector.sqlite3
systemctl start db-collector-scheduler 'db-collector-worker@*' db-collector-admin
```

Because SQLite migrations in this project are additive (new tables/columns,
never destructive `DROP`/`ALTER ... DROP`), restoring the DB backup is only
needed if something more unusual went wrong — normally the code rollback
above is enough.

## Add a new DB

Adding DB #N should **never** require editing core modules
(`scheduler.py`, `worker.py`, `collectors/pipeline.py`, migrations, ...).
You need exactly two things:

1. An **Adapter** (below).
2. A **Job** YAML file under `config/jobs/`.

## Add a new Adapter

An Adapter tells the shared pipeline how to pull DB-specific fields out of
an already-fetched page (or, for `collector_type: api`, an already-parsed
JSON payload). See `db_collector_os/adapters/base.py` and the four samples
(`sample_official_site.py`, `sample_local_business.py`,
`sample_person.py`, `sample_api.py`) for the pattern:

```python
# db_collector_os/adapters/my_new_db.py
from .base import Adapter, ExtractedRecord
from .registry import register_adapter

@register_adapter("my_new_db")
class MyNewDbAdapter(Adapter):
    name = "my_new_db"
    entity_type = "my_entity_type"
    required_fields = ("name",)

    def extract(self, common, url, raw_html):
        # `common` already has title/canonical_url/meta_description/json_ld/
        # name/address/telephone/links/social_urls/image_urls -- see
        # db_collector_os/extraction/common.py. Pull anything extra here.
        record = ExtractedRecord(
            name=common.get("name"),
            entity_type=self.entity_type,
            canonical_url=common.get("canonical_url") or url,
            confidence=0.7,
            fields={"my_field": "..."},
        )
        if not record.name:
            record.missing_required = ["name"]
        return record
```

For `collector_type: api`, override `parse_api(self, payload, url)` instead
(returns a list of `ExtractedRecord`, since one API response can list many
entities — see `sample_api.py`).

Import the module once (add it to `registry.py`'s lazy-import list, or just
import it anywhere on the startup path) so `@register_adapter` runs.

## Add a new Job

Drop a YAML file under `config/jobs/`, then run `db-collector jobs sync`
(the VPS installer/updater does this automatically). See
`config/jobs/sample_official_site.yaml` for a fully-commented example. Key
fields:

```yaml
job_id: "job_my_new_db"          # stable id; re-syncing the same id upserts
job_name: "My New DB"
category: "my_category"
target_db: "my_new_db"
target_table: "entities"
collector_type: "official_site"   # official_site | local_business | person | api
adapter: "my_new_db"              # must match @register_adapter(...) name
priority: 50                      # 100 urgent / 80 high / 50 normal / 20 low
enabled: false                    # flip to true once seed_urls are real
schedule: "@hourly"               # or "@daily" / "@every 30m" / "@minutely"
max_pages: 200                    # fetches per run_once (bounds one worker turn)
rate_limit: 2.0                   # seconds between requests to the same domain
config:
  seed_urls: ["https://example.com/"]
  discovery:
    sitemap_urls: ["https://example.com/sitemap.xml"]
    robots_seed_urls: ["https://example.com/"]
    search_queries: []            # only used if a search provider is configured
    prefecture_url_template: null # e.g. "https://example.com/area/{pref}/"
    url_pattern: null             # e.g. {template: "...{n}", start: 1, end: 100}
    internal_links: true
    related_entities: true
    allowed_domains: ["example.com"]
  phase1_conditions:
    queue_empty: true
    require_discovery_saturation: true
    consecutive_low_discovery_runs: 3
  incremental_revalidate_after_seconds: 86400
```

## Admin UI

Lightweight FastAPI + server-rendered HTML (`db_collector_os/admin/`), no
build step. Start it with `db-collector admin serve` (systemd:
`db-collector-admin.service`).

- `/` — top page: registered DB count, active/queued/running/completed/
  failed jobs, open review count, today's new/updated entities, fetch
  success/errors, CPU/RAM/disk/swap/load vs. configured thresholds.
- `/dbs` — one row per DB: phase, entity count, new/updated today, status,
  last run, next run.
- `/jobs/{job_id}` — progress, fetch-queue stats, candidate stats, run
  history, open review items for that job; pause/resume buttons.
- `/review` — every open Review Queue item across all jobs, with
  resolve/dismiss actions.

**It binds to `127.0.0.1:8787` by default** (`config/default.yaml` /
`.env`). Do not change this to `0.0.0.0` without authentication in front of
it. To access it from your workstation, use an SSH tunnel:

```bash
ssh -L 8787:127.0.0.1:8787 root@your-vps
# then open http://127.0.0.1:8787 locally
```

or put it behind a reverse proxy (nginx/Caddy) that terminates TLS and adds
authentication (basic auth or an OAuth proxy) before it ever reaches
port 8787.

## CLI

```
db-collector migrate                 # apply pending DB migrations
db-collector integrity               # PRAGMA integrity_check
db-collector health                  # JSON health report; exit 1 if unhealthy
db-collector status                  # JSON top-level summary

db-collector jobs sync               # load config/jobs/*.yaml into the registry
db-collector jobs list [--status S]
db-collector jobs show JOB_ID
db-collector jobs run JOB_ID          # run once, synchronously, in this process
db-collector jobs pause JOB_ID
db-collector jobs resume JOB_ID

db-collector queue [JOB_ID]           # fetch queue stats
db-collector review                   # list open review items
db-collector review resolve REVIEW_ID

db-collector scheduler run [--once]   # foreground loop, or a single tick
db-collector worker run [--once]      # foreground loop, or a single job
db-collector admin serve [--host H --port P]
```

## systemd

| Unit | Purpose |
| --- | --- |
| `db-collector-scheduler.service` | admits due jobs into the queue, gated by the Resource Controller |
| `db-collector-worker@N.service` | template unit; a worker instance (`worker@1`, `worker@2`, ...) that claims and runs queued jobs |
| `db-collector-admin.service` | Admin UI (`127.0.0.1:8787` by default) |

All three: `Restart=on-failure`, enabled for boot, `WorkingDirectory=/root/tools/db_collector_os`,
run via `.venv/bin/db-collector`, logs to journald
(`journalctl -u db-collector-worker@1 -f`, etc). Installed automatically by
`install_vps.sh`; to add a second worker instance:

```bash
systemctl enable --now db-collector-worker@2.service
```

## Backup

```bash
./scripts/backup.sh
```

Backs up the SQLite DB (via `sqlite3 .backup`, WAL-safe, with a plain-copy
fallback if the `sqlite3` CLI isn't installed), `config/`, and `.env` into
`var/backups/<UTC timestamp>/`. Keeps the most recent 14 backups by default
(`DB_COLLECTOR_BACKUP_KEEP`). `update_vps.sh` calls this automatically
before every update.

## Troubleshooting

- **`db-collector health` / `scripts/healthcheck.sh` report unhealthy** —
  the JSON output names the failing check (DB integrity, a stale `running`
  job, resource thresholds, ...). `stale_jobs` lists jobs whose worker
  likely died; the next Worker tick recovers them automatically
  (`Worker.recover_stale_jobs()`, based on `worker_stale_seconds`).
- **A job seems stuck** — check `db-collector jobs show JOB_ID` for its
  `phase`/`status`, and `db-collector queue JOB_ID` for fetch-queue state.
  A job whose fetch queue still has pending items but hasn't been claimed
  will pick up again on the next scheduler tick (`status=retry`, a short
  `next_run_at`).
- **VPS rebooted or a worker process was killed mid-job** — no action
  needed. `fetch_queue` rows persist per-URL status, `checkpoints` persists
  phase/run state, and `Worker.recover_stale_jobs()` resets orphaned
  `running` jobs to `retry` on the next tick — the job resumes rather than
  restarting from scratch.
- **Too many open Review Queue items** — visit `/review` in the Admin UI or
  run `db-collector review`; each item's `reason` (`captcha`, `blocked`,
  `parse_failure`, `duplicate_ambiguity`, `missing_required_field`, ...)
  says why it wasn't resolved automatically.
- **A DB isn't growing** — check `/jobs/{job_id}` for discovery-saturation
  status and the fetch-queue's `failed` count; a saturated, `incremental`-
  phase job with an empty queue is expected to grow slowly (only via
  periodic revalidation + new discovery), not on every tick.
- **Resource Controller is suppressing new jobs** — `db-collector health`
  shows current CPU/RAM/swap/disk/load vs. the configured thresholds
  (`config/default.yaml: resource_thresholds`). Already-`running` jobs are
  never killed; only new admissions are throttled.

---

## VPS: first command to run

Paste this whole block on the VPS (as root). It works whether
`/root/tools/db_collector_os` doesn't exist yet, exists as an empty/
uninitialized git repo, or already has `origin` configured. It never
deletes anything: if the directory exists and is *not* a git repo, it stops
and tells you to move it aside instead of overwriting it.

```bash
set -e
mkdir -p /root/tools
cd /root/tools

TARGET=db_collector_os
REPO_URL=https://github.com/hiro498/db_collector_os.git

if [ ! -e "$TARGET" ]; then
    git clone "$REPO_URL" "$TARGET"
elif [ -d "$TARGET/.git" ]; then
    cd "$TARGET"
    git remote get-url origin >/dev/null 2>&1 || git remote add origin "$REPO_URL"
    git fetch origin
    if git rev-parse --verify main >/dev/null 2>&1; then
        git checkout main
        git merge --ff-only origin/main
    else
        git checkout -b main origin/main
    fi
    cd ..
else
    echo "ERROR: /root/tools/$TARGET exists and is not a git repository." >&2
    echo "Move it aside first, e.g.: mv /root/tools/$TARGET /root/tools/${TARGET}.bak" >&2
    exit 1
fi

cd "$TARGET"
chmod +x scripts/*.sh
./scripts/install_vps.sh
```
