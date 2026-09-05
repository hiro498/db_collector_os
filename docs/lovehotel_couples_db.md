# 全国ラブホテル施設DB (Nationwide Love Hotel Facility DB)

This is the **SECOND production DB** for DB Collector OS, after
美少女フィギュア公式メーカーDB (see `docs/first_production_db.md`). It reuses
that DB's lifecycle mechanisms unchanged (bootstrap/discovery/collect/
validation/phase1_complete/incremental, `continuing`/`completed`/`retry`/
`failed`/`paused` job statuses, checkpoint/resume, the Resource Controller,
the Review Queue, Evidence) -- nothing about the core pipeline, adapter
contract, scheduler, or worker was modified to add this DB.

| | |
| --- | --- |
| **Name** | 全国ラブホテル施設DB (nationwide love hotel facility DB) |
| **job_id** | `job_prod_lovehotel_couples` |
| **collector_type** | `local_business` |
| **adapter** | `lovehotel_couples` (`db_collector_os/adapters/lovehotel_couples.py`) |
| **Job file** | `config/jobs/prod_lovehotel_couples.yaml` |
| **category / target_db** | `love_hotel` / `lovehotel_facilities` |
| **Primary source** | カップルズ (couples.jp) |
| **Not sources (Phase 1)** | Happy Hotel, NAVITIME -- excluded per this DB's brief |

## Phase 1 scope

Population formation only: facility name, prefecture, city, address,
detail URL, official site URL (when present on the Couples page), a
best-effort operating-status signal, and a source facility ID. Deep
attributes (price, rooms, plans, reviews) are explicitly out of scope --
see `LoveHotelCouplesAdapter`'s class docstring and `required_fields =
("name",)` (nothing else is required for a record to be accepted; missing
optional fields are stored as `NULL`, never guessed).

## Why a new adapter, not `sample_local_business` or `figure_official_site`

Per this task's own rules: `figure_official_site` is Good Smile-specific
(schema.org `Product`) and must not be repurposed; sample adapters are
never used as production adapters. `lovehotel_couples.py` is a new file,
registered under its own name (`lovehotel_couples`) in
`adapters/registry.py`, using the existing generic `local_business`
`collector_type` (`LocalBusinessCollector` is already a thin pass-through
over `BaseCollector` -- see `collectors/local_business.py`) exactly as the
architecture intends: one new adapter + one new job, zero core changes.

## The real facility URL scheme is now confirmed

A later revision of this task gave this DB a confirmed real fact it did not
previously have: a genuine Couples facility detail page is

```
https://couples.jp/hotel-details/{numeric_id}
```

(worked example: `https://couples.jp/hotel-details/1238`), and
`/prefectures/`, `/articles/`, `/themes/`, `/movies`, `/hotel-groups/`,
`/users/` are confirmed NOT facility pages. A derived URL like
`/hotel-details/1238/review`, `/hotel-details/1238/rooms`,
`/hotel-details/1238/coupon`, or `/hotel-details/1238/plan` (with or
without a query string/fragment, with or without `www.`) refers to the
*same* facility and must canonicalize to the same
`https://couples.jp/hotel-details/1238`.

This is what `db_collector_os/discovery/lovehotel_couples.py`
(`canonicalize_couples_facility_url`, `is_couples_facility_url`,
`extract_couples_facility_urls`, `extract_navigation_urls`,
`extract_prefecture_entry_urls`, `discover_prefecture_facilities`,
`discover_all_prefectures`) is built around -- see "Nationwide facility
discovery module" below. `LoveHotelCouplesAdapter._extract_facility_id`
(the adapter's own per-page facility-ID/classification signal) now reuses
`canonicalize_couples_facility_url` too, replacing an earlier "any 3+ digit
URL path segment" heuristic that this task's own production audit found was
misclassifying non-facility pages (`/articles/1234`, `/themes/456`, ...) as
facilities -- see `tests/test_lovehotel_couples_adapter.py` and
`tests/test_lovehotel_couples_facility_discovery.py`.

**Still not independently confirmed from this authoring environment: the
real prefecture/city/area-listing/pagination navigation URL scheme.** The
task's brief tells us `/prefectures/` exists and is not itself a facility
page (very likely the prefecture entry point), but not the shape of
whatever municipality/area/search-result/pagination pages sit between a
prefecture entry point and its facility links. `config_json.discovery` for
`job_prod_lovehotel_couples` (the generic, domain-scoped `internal_links`
engine every other page-discovery job uses) is therefore left **unchanged**
-- still scoped only by domain
(`allowed_domains: [couples.jp, www.couples.jp]`), no
`product_url_pattern` -- restricting it to a guessed nav-URL pattern risks
silently excluding real navigation pages, exactly as this doc warned
before. The new discovery module below solves nationwide facility discovery
a different way: `is_couples_listing_or_navigation_url` is a *denylist*
(same host, not one of the confirmed non-facility content silos), not a
guessed allowlist, so it can traverse whatever real nav structure the site
actually uses without needing to know its shape in advance.

## This environment (and this later session) has no outbound web access to couples.jp

Confirmed originally: the agent network proxy's own status endpoint
recorded a `connect_rejected` (`gateway answered 403 to CONNECT`) for
`couples.jp:443` when this DB's Step 2 (site-structure verification) was
attempted. Re-confirmed again for the nationwide-discovery-module revision
of this task (same `connect_rejected` policy denial via
`http://127.0.0.1:<port>/__agentproxy/status`) -- this authoring
environment's network policy blocks couples.jp specifically, independent of
which session runs in it. This is the exact same situation
`docs/first_production_db.md` already documents for `www.goodsmile.com`.

Concrete consequence for this revision: `db-collector couples
discover-dry-run` (see below) could not be run against the live site from
here. It WAS run for real (default, live-network mode) and its result --
all 47 prefectures failing at the very first step (the top-page fetch
itself is policy-blocked, so zero prefecture entry URLs are ever found) --
is saved under `var/discovery_dryrun/LIVE_ATTEMPT_*` as the honest record of
that attempt. A second run with `--fixtures-dir` against a synthetic,
hand-built 47-prefecture site (`var/discovery_dryrun/SIMULATED_*`) validates
that the discovery algorithm itself (BFS traversal, pagination following,
canonicalization, nationwide dedup, contamination checks, ok/empty/failed
classification for all 47 prefectures) works correctly end-to-end -- it is
NOT real couples.jp data. **The VPS operator (real HTTP access) must run
the same command for real** (`db-collector couples discover-dry-run`, no
`--fixtures-dir`) to get real nationwide facility counts -- see "Nationwide
facility discovery module" below.

robots.txt for couples.jp is likewise unverified from here.
`fetching/client.py`'s `FetchEngine` already checks robots.txt for every
request regardless of job config (`respect_robots=True` by default, used
unmodified) -- this job adds no override, and `couples discover-dry-run`'s
live mode uses the same `FetchEngine` with `respect_robots=True`. The VPS
operator should still re-confirm robots.txt content and general site
behavior as part of the same kind of preflight
`scripts/run_goodsmile_phase1_batch*.sh` already runs for the first
production DB, before ever enabling this job.

## Nationwide facility discovery module (`discovery/lovehotel_couples.py`)

A dedicated, couples.jp-specific discovery module, separate from the
generic `discovery/internal_links.py` engine `job_prod_lovehotel_couples`'s
own `config_json.discovery` still uses unchanged (see above) -- this module
is NOT wired into that job's live fetch_queue/collection pipeline yet. It
exists to answer one question safely and repeatably, without ever touching
any database or enabling/resuming the production job: **what is the full
population of real Couples facility URLs, nationwide, reachable from public
navigation alone?**

- `canonicalize_couples_facility_url(url)` / `is_couples_facility_url(url)`
  -- the confirmed `/hotel-details/{id}` shape, collapsing every derived
  URL (`/review`, `/rooms`, `/coupon`, `/plan`, a tracking query string, a
  trailing slash, `www.` vs. apex) to one canonical form per numeric id.
- `is_couples_listing_or_navigation_url(url)` -- same-host, not a facility
  URL, not one of the confirmed non-facility content silos (denylist, not a
  guessed allowlist -- see above).
- `extract_couples_facility_urls(html, base_url)` /
  `extract_navigation_urls(html, base_url)` -- per-page link extraction
  into those two categories.
- `extract_prefecture_entry_urls(html, base_url)` -- finds each of the 47
  prefectures' real entry URL by matching anchor TEXT against
  `discovery.prefecture.PREFECTURES`' exact official names, never a guessed
  URL template.
- `discover_prefecture_facilities(...)` -- a load-bounded (`max_pages`)
  breadth-first crawl from one prefecture's entry point, following
  navigation links (including pagination) and collecting every facility
  link found, distinguishing `"ok"` / `"empty"` (genuinely zero, pages DID
  fetch) / `"failed"` (entry point found but nothing fetchable) /
  `"no_entry_url"` (the prefecture's entry link itself was never found) --
  a zero-facility prefecture is never silently treated as a success.
- `discover_all_prefectures(...)` -- runs the above for all 47 prefectures
  in a fixed order, aggregating raw/canonical/unique facility-URL counts,
  duplicate/contamination checks, and per-prefecture provenance.
- `FixtureFetchEngine` -- an offline, `fetch_engine`-compatible stand-in
  reading local HTML files via a `manifest.json`, used by this module's own
  tests and by `db-collector couples discover-dry-run --fixtures-dir` in an
  environment (like this one) without outbound access to couples.jp.

### Running it

```bash
# Live (default) -- requires real outbound HTTPS to couples.jp; respects
# robots.txt; never writes to any database; never touches job_prod_lovehotel_couples.
db-collector couples discover-dry-run

# Offline / algorithm validation only (no live network) -- see
# var/discovery_dryrun/SIMULATED_* for what this produces:
db-collector couples discover-dry-run --fixtures-dir /path/to/fixture/site
```

Both modes write a plain-text report (`47_PREFECTURES_VISITED`,
`FAILED_PREFECTURES`, one `PREFECTURE_NN_NAME=...` line per prefecture,
`RAW_FACILITY_URLS`/`CANONICAL_FACILITY_URLS`/`UNIQUE_FACILITY_IDS`,
`DUPLICATE_FACILITY_IDS`/`REVIEW_URL_CONTAMINATION`/
`NON_FACILITY_URL_CONTAMINATION`, `DISCOVERY_COMPLETE`) and a JSON detail
file (every discovered facility with its `prefecture` and
`discovered_from_url`) under `<home_dir>/discovery_dryrun/` (override with
`--output-dir`). Exit code is non-zero iff any prefecture failed.

## Facility-vs-listing classification (no guessed HTML selectors)

`LoveHotelCouplesAdapter.extract()` treats a fetched page as a genuine
facility page if ANY of these generically-observable signals is present:

1. A schema.org `LodgingBusiness` / `Hotel` / `LocalBusiness` JSON-LD
   block (the strongest signal, reusing `extract_common`'s existing
   JSON-LD parsing -- same mechanism `sample_local_business` and
   `figure_official_site` already rely on).
2. A postal-code-shaped address (`〒nnn-nnnn ...`) found in the page's own
   visible text -- a deliberately conservative fallback for sites (many
   small Japanese directories) that don't publish JSON-LD. This is a
   generic Japanese postal-code pattern, not a Couples-specific selector.
3. A confirmed `/hotel-details/{numeric_id}` URL (or a derived `/review`,
   `/rooms`, `/coupon`, `/plan`, ... sub-path of one) in the page's own
   canonical URL or fetched URL, via
   `discovery.lovehotel_couples.canonicalize_couples_facility_url` -- the
   precise, confirmed signal that replaced this adapter's earlier "any 3+
   digit URL path segment" guess (see "The real facility URL scheme is now
   confirmed" above).

A page with **none** of these is skipped silently
(`ExtractedRecord.skip = True`) -- the same "confirmed non-entity page"
contract `figure_official_site` uses for Good Smile's listing pages, so a
prefecture/area listing page never floods the Review Queue. A page that
*does* look like a facility page but has no extractable name still goes to
the Review Queue (`missing_required`) -- that is a real data-quality
problem worth a human's attention, not something to drop silently.

Prefecture and city are extracted from the address text only when the
*exact* known prefecture name (`discovery/prefecture.py::PREFECTURES`,
reused rather than duplicated) is literally present in it; otherwise both
stay `NULL`. Operating status is only ever set to `"closed"`, when an
explicit Japanese "this facility has closed" marker (`閉店`/`閉業`/`廃業`/...)
is found in the page text -- absence of such a marker leaves it `NULL`
("unknown"), never assumed `"open"`. See
`tests/test_lovehotel_couples_adapter.py` for the full matrix (JSON-LD
present, JSON-LD absent + text fallback, missing official URL, explicit
closed marker, missing name -> review, listing page -> skip, malformed
page -> skip without crashing, facility-ID-only signal keeps
prefecture/city `NULL` rather than guessing them).

## Discovery

`config_json.discovery`:

```yaml
discovery:
  sitemap_urls: []
  robots_seed_urls:
    - "https://couples.jp/"
  internal_links: true
  related_entities: false
  allowed_domains:
    - "couples.jp"
    - "www.couples.jp"
```

- `robots_seed_urls` picks up any `Sitemap:` directive couples.jp's own
  robots.txt declares (`discovery/robots_sitemap.py` +
  `discovery/sitemap.py`), without this job guessing a sitemap path.
- `internal_links` is the main discovery mechanism: every same-domain link
  found on an already-fetched page becomes a candidate (see
  `tests/test_lovehotel_couples_discovery.py`), so the crawl naturally
  grows homepage -> area/prefecture listing pages -> facility pages ->
  pagination, all discovered from real, page-embedded `<a href>` links,
  never invented. Duplicate URLs (including a normalize-away-able tracking
  query string) collapse to one `entity_candidates` row and one
  `fetch_queue` row via the existing `normalize_url()` +
  `UNIQUE(job_id, url)` infrastructure -- unchanged, reused as-is.
- `related_entities` (JSON-LD `sameAs` following, see
  `discovery/related_entity.py`) is **deliberately off**. That method has
  no domain restriction at all -- if a facility's `sameAs` ever pointed at
  its own official site, enabling it would grow this crawl into "Couples
  -> official site -> whatever THAT page links to -> ...", exactly what
  this DB's brief says must never happen (STEP 10: 公式サイト→外部リンク→
  無限crawl must never happen). `official_url` is still captured (with
  Evidence) as a stored field -- it is simply never auto-enqueued into this
  job's own `fetch_queue`. `allowed_domains` (couples.jp only) is the
  second, independent layer of the same containment: even if some future
  config change turned `related_entities` back on, `internal_links`
  discovery would still never enqueue an off-domain link, and any
  official-site URL that *did* somehow get queued would still go through
  the same robots.txt/SSRF-guarded `FetchEngine` as everything else.

Before Phase 1 ever runs, `db-collector couples discover-dry-run` (see
above) gives the same per-prefecture facility-URL population as a read-only
preview -- URLs only (no name/address/etc. yet), never written to any
database. 47-prefecture coverage of the *collected* entities is tracked
implicitly, not via a new schema: once Phase 1 has run, `SELECT
data_json->>'prefecture', COUNT(*) FROM entities
WHERE job_id='job_prod_lovehotel_couples' GROUP BY 1` (or the equivalent
via `EntityStore`) gives a per-prefecture facility count directly from
existing entity data -- no new table or column was added for this, per
this task's own rule against unnecessary schema changes. A prefecture
returning zero facilities is not, by itself, treated as an error or a
reason to retry indefinitely -- the existing, unmodified saturation logic
(`discovery/saturation.py`, `consecutive_low_discovery_runs`) already
governs when Phase 1 stops trying, for this job exactly as for any other.

## Deduplication

Reuses the existing `Deduplicator` (`deduplication/matcher.py`,
`deduplication/fingerprint.py`) completely unmodified:

1. **`source_facility_id`** (the adapter's best-effort numeric ID from the
   page's own URL) is passed as `ExtractedRecord.external_id`, the
   strongest fingerprint signal -- two different URLs for the same
   facility ID always merge into one entity
   (`tests/test_lovehotel_couples_adapter.py::
   test_facility_id_and_fingerprint_shared_across_different_urls_for_same_facility`,
   `tests/test_lovehotel_couples_pipeline_integration.py::
   test_duplicate_across_urls_merges_via_facility_id`).
2. **`canonical_url`** is the next fingerprint signal, used automatically
   whenever no facility ID could be extracted.
3. **Normalized name** (fuzzy path): two facilities can legitimately share
   an exact name (chain hotels, common naming) -- the existing matcher
   routes a same-name-but-conflicting-address/domain/telephone case to the
   Review Queue rather than either silently merging or silently creating a
   duplicate entity (`tests/test_lovehotel_couples_pipeline_integration.py::
   test_same_name_different_address_is_never_auto_merged`). Nothing here
   was changed to add address-based matching -- the existing conflict
   check in `Deduplicator._conflicts()` already compares address when
   present.

## Evidence

Reuses `EntityStore`/`EvidenceStore` unmodified. Every field on a created/
merged entity (`name`, `address`, `prefecture`, `city`, `official_url`,
`operating_status`, `source_name`, `source_facility_id`, ...) gets a
matching `evidence` row recording the fetched source URL, timestamp, and
confidence (0.75 when a JSON-LD business block was present, 0.55
otherwise) -- see `BaseCollector._handle_extracted()`, not touched by this
change.

## Production job (`config/jobs/prod_lovehotel_couples.yaml`)

Ships `enabled: false`, same policy as `prod_figure_official_site.yaml`:
enabling happens only on the VPS via `db-collector jobs enable`/`resume`,
never by flipping the YAML in Git. Conservative first-batch numbers,
matching the first production DB's own validated starting point exactly
(`max_pages: 30`, `concurrency: 1`, `rate_limit: 5.0`,
`max_drain_wait_seconds: 180`) -- this environment cannot verify
couples.jp's real server behavior/capacity, so these are safe defaults,
not a tuned guess. `schedule: "@daily"` is the steady-state fallback only;
during active Phase 1 crawling the job reschedules itself every
`worker_poll_interval_seconds` via `JobStatus.CONTINUING` whenever
`fetch_queue` still has pending work (`worker.py::run_job_and_record`,
unmodified) -- this is not "one full crawl per day", exactly as already
documented for the Good Smile job.

## VPS deploy (mirrors `docs/first_production_db.md`'s pattern)

```bash
cd /root/tools/db_collector_os
git pull --ff-only
.venv/bin/db-collector jobs migrate   # no-op here: no schema change shipped
.venv/bin/db-collector jobs sync      # registers job_prod_lovehotel_couples, enabled=false
.venv/bin/db-collector jobs reseed job_prod_lovehotel_couples
# -- confirm couples.jp robots.txt / general reachability with real HTTP
#    access before the next two commands --
.venv/bin/db-collector jobs enable job_prod_lovehotel_couples
.venv/bin/db-collector jobs resume job_prod_lovehotel_couples
```

Stop/pause and resume semantics are identical to the first production DB
(see `docs/first_production_db.md` "Stop / pause" / "Resume") -- nothing
job-specific was added here, since the existing mechanisms already apply
unchanged: pausing only stops new runs from being admitted; resuming
continues exactly where `fetch_queue`/`checkpoints`/`entity_candidates`
left off.

## Safety summary

- No existing table dropped, no existing row deleted, no destructive
  migration: this DB adds zero schema changes (uses the existing generic
  `entities`/`evidence`/`entity_candidates`/`fetch_queue`/`jobs` tables
  exactly as every other job does, distinguished only by `job_id`/
  `category`/`target_db`, all plain string columns already in
  `migrations/0001_init.sql`).
- No existing job's `enabled`/`status` was touched. The 4 sample jobs and
  `job_prod_figure_official_site` remain exactly as they were (see
  `tests/test_production_job_lovehotel_couples.py::
  test_jobs_sync_registers_the_production_job_disabled`).
- No dummy/example.com job was added to production config -- the only
  YAML this change adds is `config/jobs/prod_lovehotel_couples.yaml`,
  shipped `enabled: false`.
- Happy Hotel and NAVITIME appear nowhere in this job's config or adapter
  (enforced by `tests/test_production_job_lovehotel_couples.py::
  test_production_job_yaml_exists_and_is_well_formed`).
- `figure_official_site.py` was not modified.
- No real-site crawling was executed from this authoring environment (no
  outbound access exists to perform any).

### Safety summary (nationwide-discovery-module revision)

- `config/jobs/prod_lovehotel_couples.yaml` was **not modified** -- still
  `enabled: false`, same `discovery` config, same `rate_limit`/`max_pages`/
  `concurrency`. This revision adds a new, separate discovery module and
  CLI command; it does not change what the production job itself does.
- `job_prod_lovehotel_couples`'s DB `status` (`paused`, per the task brief)
  was not touched by anything in this revision -- `couples
  discover-dry-run` never opens a `Database`/`JobRegistry` at all (see
  `tests/test_couples_discovery_cli.py::
  test_production_job_stays_paused_and_disabled_and_untouched_by_this_change`).
- `couples discover-dry-run` never writes to any database, any
  `fetch_queue`, or any `entity_candidates`/`entities` row -- it is a pure
  in-memory crawl that only ever writes a `.txt`/`.json` report to disk.
- The only production-adapter change is `LoveHotelCouplesAdapter`'s
  facility-ID signal (see "The real facility URL scheme is now confirmed"),
  scoped entirely to `db_collector_os/adapters/lovehotel_couples.py`; no
  other adapter, collector, discovery engine, or job was modified (see
  `tests/test_lovehotel_couples_facility_discovery.py::
  test_module_does_not_touch_other_categories` and the full existing test
  suite, unmodified elsewhere and still green).
- Existing `couples_facility_detail_*.html` fixtures and their tests were
  updated from a placeholder `/hotel/{id}/` URL shape (documented in their
  own comments as "a reconstruction, not a live scrape") to the
  now-confirmed real `/hotel-details/{id}` shape -- this only changes the
  URLs asserted against in lovehotel-couples-specific tests, not any
  behavior outside this DB.
