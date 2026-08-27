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

**Decision: seed from the confirmed real Scale Figure Reference List
(`https://www.goodsmile.com/en/scalefigure_list`) plus the one confirmed
real product page; `internal_links` (+ `related_entities`) discovery,
scoped by a `discovery.product_url_pattern` filter to product-detail and
scalefigure_list URLs only. No sitemap/category/URL-ID-range was guessed.**

`GOODSMILE_LIST_URL=https://www.goodsmile.com/en/scalefigure_list` --
given directly as a confirmed-real URL. `PRODUCT_URL_PATTERN=/en/product/
(\d+)/<slug>` -- derived from the one confirmed real product page's URL
(`.../en/product/1141716/Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2B
toridamono`), not guessed.

This environment (every Claude Code session that has worked on this job)
has no outbound web access -- every attempt to reach `www.goodsmile.com`
(curl, WebFetch) is blocked by the network egress policy, confirmed again
for this revision. Per this task's own instruction ("URLやサイト構造を
推測してはいけない"), that means **pagination could not be verified**:
`PAGINATION_METHOD=unknown (not implemented)`. Rather than guess a
`?page=N` query-param scheme or any other pagination mechanism, this job
only ever follows links **actually found on pages it has itself fetched**:

- `discovery/internal_links.py` now accepts an optional
  `product_url_pattern` regex. A link is kept only if it matches
  `/en/product/(\d+)/` (capturing the numeric product ID) **or**
  `/en/scalefigure_list` (so if the listing page's own HTML contains a
  same-path "next page" `<a href>`, whatever its query string looks like,
  it keeps getting followed -- without this job ever having to know that
  scheme in advance). Everything else on the same domain (about/contact/
  cart/account/privacy/...) is filtered out before it can waste any of the
  30-page budget, and `/search` structurally can never match either
  branch, so it is unreachable regardless of robots.txt.
- The captured product ID also fingerprints candidates
  (`discovery/engine.py`): two different URLs (different slug) for the
  same numeric ID collapse into one `entity_candidate` before either is
  ever fetched, rather than relying only on the downstream
  fingerprint-by-`external_id` merge to catch it after two wasted fetches.

If the real listing page turns out to paginate some other way (an API
call, infinite scroll with no plain `<a href>`, ...), batch #1 will simply
discover only what's linked from the page(s) it does see -- bounded,
never wrong, and a safe basis for deciding whether batch #2 needs a
verified additional seed URL (found by the VPS operator, who has real
HTTP access, not guessed from here).

**Multi-manufacturer/brand**: the list page is known to mix Good Smile
Company, Max Factory, and other official brands. Nothing in this job or
adapter hardcodes a manufacturer/brand -- `figure_official_site.py` always
reads `brand`/`manufacturer` from each product page's own JSON-LD/
dataLayer (see `tests/test_goodsmile_adapter.py::
test_brand_and_manufacturer_are_never_hardcoded_to_good_smile`). Every
product legitimately listed on Good Smile's own site is in scope for this
DB's population, regardless of which company actually makes it;
`entities.domain` (`www.goodsmile.com`, the *source*) and
`entities.data_json.brand`/`.manufacturer` (whichever company the page
itself names) are tracked as separate fields, never conflated.

## Phase 1 batch #1 configuration

```yaml
seed_urls:
  - https://www.goodsmile.com/en/scalefigure_list
  - https://www.goodsmile.com/en/product/1141716/Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2Btoridamono
discovery:
  product_url_pattern: "/en/product/(\\d+)/|/en/scalefigure_list"
max_pages: 30         # hard per-run_once() ceiling regardless of discovery breadth
max_depth: 2           # recorded for intent; not yet enforced anywhere in the
                        # pipeline (discovery methods don't track hop count --
                        # a known, pre-existing gap, not something this change
                        # papers over). max_pages is the real safety bound.
concurrency: 1
rate_limit: 5.0         # seconds between requests to the same domain
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
`scripts/run_goodsmile_phase1_batch1.sh`), never by flipping the YAML.

## VPS: run Phase 1 batch #1

```bash
cd /root/tools/db_collector_os
./scripts/run_goodsmile_phase1_batch1.sh
```

Preflight (all in your foreground shell, all read-only except the backup
and the job-registry sync/enable at the very end, only reached if every
check passes): git clean/fetch/ff-only/HEAD-vs-origin, DB backup, DB
integrity, systemd services active, Admin UI HTTP 200, the existing
Resource Controller's admission gate (reads current CPU/RAM/swap/disk/load
-- never modifies swap or thresholds), a live robots.txt re-check against
both seed URLs, and confirmation the 4 sample jobs are still disabled. Any
failure prints `[BLOCK]`/`[FATAL]` and leaves the job untouched
(`GOODSMILE_PHASE1_BATCH1=FAIL`, `PRODUCTION_CRAWL_STARTED=NO`) -- safe to
fix and re-run.

SSH-disconnect-safe: preflight + enabling the job run in your shell; the
actual crawl always runs through the already-persistent
`db-collector-worker@1.service` (unaffected by your SSH session either
way, with or without systemd-run); the post-batch wait/report/success-gate/
auto-disable step runs via a single named `systemd-run` transient unit
(`db-collector-phase1-batch1-goodsmile`) so it keeps going, and writes its
report to `var/reports/`, even if you disconnect. See the script's own
header comment, `scripts/_phase1_batch1_watch_and_report.sh` (the watcher;
evaluates the batch #1 success gate and always disables the job
afterward), `scripts/_phase1_batch1_report.py` (the report generator), and
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
