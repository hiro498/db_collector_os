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
| **Source** | Good Smile Company official site (`www.goodsmile.com`) |

## Why this DB first

Selected from the candidate list (order suits, tanning salons, gyms, love
hotels, live houses, belly/Tahitian dance schools, joshi puroresu, idol/
talent agencies, K-pop agencies, tires, wheels, Honda VEZEL variants,
bishoujo figures, competitive swimwear, ...) for how well it exercises the
platform, not for standalone business value: a single manufacturer's own
catalog is a clear single source of truth, low robots/load risk, and the
best-validated collector_type (schema.org `Product` JSON-LD, not guessed
site-specific scraping). See the full original rationale in git history
(`docs/first_production_db.md` @ the commit that added this job) -- kept
short here since the DB has since moved from "selected" to "proven".

## Status: single-product proof PASSED, Phase 1 batch #1 configured

**Production proof** (one known, real Good Smile product page):
`FIRST_PRODUCTION_PROOF=PASS`, `ENTITY_COUNT=1`, `EVIDENCE_COUNT=13`,
`RUN_ERRORS=0`, `OPEN_REVIEWS=0`, Admin HTTP 200, scheduler/worker/admin all
active. Real URL used:
`https://www.goodsmile.com/en/product/1141716/Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2Btoridamono`

Two bugs surfaced by that run and were fixed (with regression tests):

1. **HTML entity decoding.** `entity.name` was stored as `"Rikka Takarada
   &amp; Akane Shinjo feat. toridamono"` instead of the decoded `"Rikka
   Takarada & Akane Shinjo feat. toridamono"`. Root cause: `<script>`
   content is "raw text" per the HTML spec, so the parser never decodes
   entities inside a `<script type="application/ld+json">` block the way
   it does ordinary text nodes -- when a site's templating auto-escapes a
   JSON-LD payload it doesn't recognize as HTML, the literal `&amp;`
   survives `json.loads()` verbatim. Fixed in `extraction/jsonld.py`
   (recursively decodes every string value in a parsed JSON-LD block) and,
   defensively, in `extraction/common.py`'s own text fields. New shared
   helper: `normalization/html_entities.py`. See
   `tests/test_html_entity_decode.py`.
2. **`run_history` never finished by `db-collector jobs run`.** The job
   itself completed correctly (fetched=1, inserted=1, error=0), but the
   `run_history` row stayed at `status='running'`, `fetched_count=0`,
   `duration_seconds=NULL` forever. Root cause: the CLI's `jobs run`
   command called the collector directly and never called
   `run_history.finish()` (only `Worker.run_one_job()` did). Fixed by
   extracting the "run + durably record the outcome" logic into
   `worker.run_job_and_record()`, now used by **both**
   `Worker.run_one_job()` and `db-collector jobs run` so the two paths can
   never drift apart again -- including the failure path (a run that fails
   before `run_history.start()` is even reached, e.g. an unresolvable
   adapter name, now still gets a `status='failed'` row instead of no row
   at all). See `tests/test_cli.py::test_jobs_run_finishes_run_history_on_*`.

**Adapter field coverage**, expanded from the 1-product test: JSON-LD
`Product` stays the primary/authoritative source; new
`extraction/datalayer.py` adds a conservative (strict-JSON-only, never
overrides JSON-LD) fallback from the page's `dataLayer` -- Google
Analytics 4's own standard Enhanced Ecommerce parameter names
(`item_id`/`item_name`/`item_brand`/`item_category`/`item_category2`/
`price`, confirmed present on the real page), plus Good Smile's own
`product_master_code`/`product_name`/`image_url`/`reservation_deadline`
siblings observed in the same `dataLayer.push()` call. `reservation_deadline`
has no schema.org `Product` equivalent at all and is common for pre-order
figures, so it's now a first-class (dataLayer-only) field. See
`tests/test_goodsmile_adapter.py` (fixture reconstructed from the confirmed
proof -- not a live scrape, since this environment has no outbound web
access; see "Phase 1 discovery method" below).

## Phase 1 discovery method

**Decision: `internal_links` (+ `related_entities`), seeded from the one
verified real product page. No listing/category/sitemap/URL-pattern URL was
guessed.**

This environment (the Claude Code session that implemented Phase 1 batch
#1) has no outbound web access -- every attempt to reach
`www.goodsmile.com` (curl, WebFetch) is blocked by the network egress
policy. Per this task's own instruction ("URLやサイト構造を推測しては
いけない"), that means no candidate listing page, category page, sitemap
URL, or product-ID URL pattern could be verified, so none of those were
added. What *is* known, from information given directly in this task (not
guessed):

- `robots.txt` (confirmed content): `User-agent: *` / `Disallow: /*/search`
  -- so search-based discovery is both unavailable in this codebase
  (`config/default.yaml` ships `search_provider: ""`) and explicitly
  disallowed by the site; neither is used.
- One verified, working product page (the proof URL above), whose JSON-LD
  and `dataLayer` were directly observed.

Given that, `internal_links` discovery (`db_collector_os/discovery/
internal_links.py`, already implemented and tested) is the only expansion
method that doesn't require assuming anything about site structure: it
only ever follows `<a href>` targets **found on pages this job has itself
already fetched**, scoped to `allowed_domains: [www.goodsmile.com]`. A
product detail page routinely links to its category and to related
products (the fixture's reconstructed links include exactly that shape),
so this should organically discover more of the catalog. `related_entities`
(schema.org `sameAs` links in JSON-LD) is enabled too, for the same
reason -- it's a page-content-driven method, not a URL guess.
`url_pattern` (guessing an ID range) and `sitemap_urls` (guessing a
sitemap path) are deliberately **not** used.

If, when running the activation/batch script below (which runs on the VPS,
where real HTTP access exists), the operator notices an actual listing/
category page or a real sitemap URL while watching Phase 1 progress, adding
it to `config/jobs/prod_figure_official_site.yaml`'s `seed_urls` or
`discovery.sitemap_urls` is a reasonable, safe follow-up -- just don't
invent one from here.

## Phase 1 batch #1 configuration

```yaml
max_pages: 30        # hard per-run_once() ceiling regardless of discovery breadth
max_depth: 2          # recorded for intent; not yet enforced anywhere in the
                       # pipeline (discovery methods don't track hop count --
                       # a known, pre-existing gap, not something this change
                       # papers over). max_pages is the real safety bound.
concurrency: 1
rate_limit: 5.0        # seconds between requests to the same domain
schedule: "@daily"
```

`phase1_conditions`: queue empty, discovery saturated for 3 consecutive
low-yield runs, error rate <= 50%, at least 1 entity collected. Kept as
the task's suggested conservative starting point (30 / 1 / >=3s) since
this environment can't verify the real catalog's size or server behavior
to justify anything looser.

Existing safety mechanisms this job relies on unchanged (see README for
each): 404/403/429/5xx handled by `fetching/client.py` + `fetching/
queue.py` retry/backoff (never spins forever, isolates one bad URL from
the rest); duplicate URLs deduped via `normalize_url()` + a `UNIQUE
(job_id, url)` constraint on `fetch_queue`; checkpoint/resume via
`checkpoints` + per-URL `fetch_queue` status; the Resource Controller
gates new job admission (never kills a running job); the 4 sample jobs
stay `enabled: false` in every job-registry-touching path this change
adds (verified by `tests/test_production_job_figure.py`).

**Repo state**: this file's job YAML ships `enabled: false`, as required --
enabling happens only on the VPS via `db-collector jobs enable` (see
`scripts/phase1_batch1_goodsmile.sh`), never by flipping the YAML.

## VPS: run Phase 1 batch #1

```bash
cd /root/tools/db_collector_os
./scripts/phase1_batch1_goodsmile.sh
```

SSH-disconnect-safe: preflight checks and enabling the job run in your
shell; the actual crawl always runs through the already-persistent
`db-collector-worker@1.service` (unaffected by your SSH session either
way), and the post-batch wait/report/auto-disable step runs via a single
named `systemd-run` transient unit so it keeps going, and writes its
report, even if you disconnect. See the script's own header comment and
`scripts/activate_first_production_db.sh` (the original 1-product
activation script; still valid, just superseded by the batch script above
for anything beyond a single proof page) for more detail.

## Stop / pause

```bash
.venv/bin/db-collector jobs pause job_prod_figure_official_site
```

Pausing only stops *new* runs from being admitted -- it does not kill an
already-`running` invocation (the Resource Controller/Worker never force-
kill a running job; see README "Resource Controller").

## Resume

```bash
.venv/bin/db-collector jobs enable job_prod_figure_official_site
.venv/bin/db-collector jobs resume job_prod_figure_official_site
```

Resuming picks up exactly where the job left off: `fetch_queue` rows keep
their per-URL status, `checkpoints` keeps phase/run state, and
`entity_candidates` keep their discovery status -- nothing restarts from
scratch (see README "Checkpoint / Resume" / "Reboot recovery"). Recall the
`jobs sync` ordering note: `jobs sync` always resets `enabled` to whatever
the YAML says (`false`), so re-enabling after any future `jobs sync` (e.g.
from `update_vps.sh`) needs `jobs enable` again -- it doesn't stick across
a sync unless the YAML itself is changed.
