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

## This environment has no outbound web access to couples.jp

Confirmed for this revision: the agent network proxy's own status endpoint
recorded a `connect_rejected` (`gateway answered 403 to CONNECT`) for
`couples.jp:443` when this DB's Step 2 (site-structure verification) was
attempted. This is the exact same situation `docs/first_production_db.md`
already documents for `www.goodsmile.com`, and this DB follows the same
discipline: **no URL pattern, pagination scheme, or HTML structure below is
guessed as verified fact.** The only fact treated as confirmed real is the
domain itself, `https://couples.jp/`, given directly in this DB's brief.

This has two concrete consequences, different from the (also-unverified,
but narrower) Good Smile case:

1. **No `product_url_pattern`/facility-URL regex is configured.** Good
   Smile's job could scope `internal_links` to a pattern because the
   *product* URL shape was confirmed directly by a real, given URL (the one
   product page). Couples gave no equivalent confirmed facility or
   area-listing URL. Scoping `internal_links` to a guessed pattern here
   risks silently excluding the very prefecture/area-listing pages a
   nationwide crawl needs to traverse to ever reach a facility page at all
   -- so `discovery.internal_links` is scoped only by domain
   (`allowed_domains: [couples.jp, www.couples.jp]`), not by URL shape.
   Classifying "is this actually a facility page" is done entirely inside
   the adapter, from content actually observed on a fetched page (see
   next section) -- never from a URL regex.
2. **No `prefecture_url_template` is configured**, even though
   `discovery/prefecture.py` already supports exactly this pattern
   generically (`https://example.com/area/{pref}/`-style expansion across
   all 47 prefectures) and was clearly anticipated for a DB like this one.
   Without a confirmed real per-prefecture URL template, populating that
   config key would be exactly the "推測してはいけない" (must-not-guess)
   URL this task's rules forbid. Coverage of all 47 prefectures is instead
   expected to emerge from ordinary internal-link crawling: a nationwide
   hotel directory of this kind conventionally exposes a persistent
   navigation menu linking every prefecture from (effectively) every page,
   so a domain-scoped BFS from the homepage reaches them without the job
   needing to know the URL scheme in advance. **This is an assumption, not
   a verified fact** -- flagged here explicitly so the VPS operator (who
   has real HTTP access) can confirm it, and add a verified
   `prefecture_url_template` or `product_url_pattern` in a follow-up batch
   if the real site needs it, exactly as the Good Smile job evolved its
   own discovery config across batches 1-3.

robots.txt for couples.jp is likewise unverified from here.
`fetching/client.py`'s `FetchEngine` already checks robots.txt for every
request regardless of job config (`respect_robots=True` by default, used
unmodified) -- this job adds no override. The VPS operator should still
re-confirm robots.txt content and general site behavior as part of the
same kind of preflight `scripts/run_goodsmile_phase1_batch*.sh` already
runs for the first production DB, before ever enabling this job.

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
3. A numeric ID (3+ digits) found in the page's own canonical URL path --
   best-effort only, overridable in a later batch once the real URL scheme
   is confirmed; documented in the adapter module as unverified.

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

47-prefecture coverage is tracked implicitly, not via a new schema: once
Phase 1 has run, `SELECT data_json->>'prefecture', COUNT(*) FROM entities
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
