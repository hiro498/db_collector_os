# First Production DB: 美少女フィギュア公式メーカーDB

This is `FIRST_PRODUCTION_DB` for DB Collector OS -- the first real (non-
sample) job registered on the platform, used to validate the whole pipeline
end to end on real infrastructure before onboarding the next several dozen
DBs.

| | |
| --- | --- |
| **Name** | 美少女フィギュア公式メーカーDB (bishoujo figure official manufacturer product DB) |
| **job_id** | `job_prod_figure_official_site` |
| **collector_type** | `official_site` |
| **adapter** | `figure_official_site` (`db_collector_os/adapters/figure_official_site.py`) |
| **Job file** | `config/jobs/prod_figure_official_site.yaml` |
| **category / target_db** | `figure` / `figure_official_site` |

## Why this DB first

Selected from the candidate list (order suits, tanning salons, gyms, love
hotels, live houses, belly/Tahitian dance schools, joshi puroresu, idol/
talent agencies, K-pop agencies, tires, wheels, Honda VEZEL variants,
bishoujo figures, competitive swimwear, ...) for how well it exercises the
platform, not for standalone business value:

1. **Clear single-source-of-truth pattern**: one manufacturer's own product
   catalog is the one and only first-party source per job -- no multi-
   source reconciliation needed for Phase 1.
2. **Low robots/load risk**: a manufacturer's own catalog is typically a
   few hundred products at most; `max_pages`, `rate_limit`, and
   `concurrency` can be kept small without materially slowing collection.
3. **`official_site` is the best-validated collector_type**: it relies on
   schema.org `Product` JSON-LD, a documented, vendor-neutral structure --
   not guessed, site-specific scraping. The exact same adapter pattern is
   expected to generalize to the other `official_site` candidates (tires,
   wheels, swimwear, ...) with only a Job config change.
4. **Clear entity structure**: name, brand, manufacturer, series
   (`schema.org Product.category`), scale, SKU/MPN/GTIN, price, currency,
   availability, release date, images -- a well-defined, demo-able schema.
5. **Exercises the full pipeline**: listing pages (discovered via
   `internal_links`) feeding detail pages, GTIN-based deduplication,
   evidence/provenance per field, checkpoint/resume, retry/backoff, per-
   domain rate limiting, and incremental revalidation via conditional GET
   are all exercised by `tests/test_figure_pipeline_integration.py`.
6. No paid API, no search-engine API: discovery relies only on
   `sitemap_urls` / `robots_seed_urls` / `internal_links` /
   `related_entities`, all already implemented in `discovery/`.

## Source strategy

`config/jobs/prod_figure_official_site.yaml` ships with **placeholder**
`REPLACE_ME` seed/sitemap/robots URLs and `enabled: false`. This is
deliberate: outbound web access was not available from the Claude Code
environment that implemented this job, so no specific manufacturer site's
URL or HTML structure was guessed or hard-coded (per project policy). The
adapter itself only depends on the open schema.org `Product` structure, not
on any one site's markup, so swapping in a real site is purely a config
change:

1. Pick one specific official figure-manufacturer site (check its
   `robots.txt` and terms of use first).
2. Replace every `REPLACE_ME` URL in the job YAML with real ones for that
   site.
3. `db-collector jobs sync` (or let `install_vps.sh` / `update_vps.sh` do
   it automatically).
4. Enable it (see below).

A page on the target site that carries no `Product` JSON-LD (a listing/
nav/boilerplate page) is treated by the adapter as a confirmed non-entity
page and silently skipped (`ExtractedRecord.skip`) rather than flooding the
Review Queue -- see `db_collector_os/adapters/figure_official_site.py` and
`db_collector_os/adapters/base.py` for the mechanism (this is a small,
backward-compatible addition to the shared Adapter/pipeline contract; every
pre-existing adapter is unaffected since it defaults to `False`).

## Rate limit / Phase 1 posture

Deliberately conservative for a first real production run:

- `concurrency: 1`, `rate_limit: 3.0` (seconds between requests to the same
  domain), `max_pages: 30` per run, `schedule: "@daily"`.
- `phase1_conditions`: queue empty, discovery saturated for 3 consecutive
  runs, error rate <= 50%, at least 1 entity collected.
- `incremental_revalidate_after_seconds: 604800` (weekly) once Phase 1
  completes -- a manufacturer catalog doesn't need hourly re-crawling.

These are starting values; adjust in the YAML (then `jobs sync`) once the
real site's actual size/behavior is known.

## VPS: enable and start Phase 1

After pointing the YAML at a real site and syncing it in (see [VPS
activation script](../scripts/activate_first_production_db.sh) for a
one-shot version of this):

```bash
cd /root/tools/db_collector_os
# Edit config/jobs/prod_figure_official_site.yaml first: replace every
# REPLACE_ME URL, then flip `enabled: true` in that same file -- the YAML is
# the durable source of truth for `enabled` (see note below).
.venv/bin/db-collector jobs sync
.venv/bin/db-collector jobs show job_prod_figure_official_site
```

> **Ordering note**: `jobs sync` always overwrites a job's `enabled` flag
> with whatever the YAML currently says (`ON CONFLICT ... enabled=excluded.enabled`
> in `job_registry.py`). A manual `db-collector jobs enable
> job_prod_figure_official_site` works too, but only until the *next*
> `jobs sync` (which `update_vps.sh` runs on every deploy) silently reverts
> it back to whatever the YAML says. For a change that should stick, edit
> the YAML's `enabled: true` and sync -- don't rely on the CLI toggle alone.

The scheduler (already running under systemd) picks it up on its next
tick, gated by the existing Resource Controller like any other job. Watch
it in the Admin UI (`/jobs/job_prod_figure_official_site`) or via:

```bash
.venv/bin/db-collector queue job_prod_figure_official_site
.venv/bin/db-collector review
journalctl -u db-collector-worker@1 -f
```

## Stop / pause

```bash
.venv/bin/db-collector jobs pause job_prod_figure_official_site
```

Pausing only stops *new* runs from being admitted -- it does not kill an
already-`running` invocation (the Resource Controller/Worker never force-
kill a running job; see README "Resource Controller").

## Resume

```bash
.venv/bin/db-collector jobs resume job_prod_figure_official_site
```

Resuming picks up exactly where the job left off: `fetch_queue` rows keep
their per-URL status, `checkpoints` keeps phase/run state, and
`entity_candidates` keep their discovery status -- nothing restarts from
scratch (see README "Checkpoint / Resume" / "Reboot recovery").
