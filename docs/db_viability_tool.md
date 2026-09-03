# DB viability assessment tool (`db-collector viability ...`)

Given a candidate DB theme (e.g. "アクセサリーのオーダーメイド工房"), decide
**GO / HOLD / NO-GO** by checking, in order:

1. **Phase 1 -- demand.** Does real search demand exist? A single big
   keyword is never enough on its own -- category x type x attribute x
   region x usage longtail volume is generated and aggregated alongside it.
   A theme that fails this gate is NO-GO and never reaches Phase 2.
2. **Phase 2 -- competition.** For themes that pass Phase 1, is there SEO
   room to win the *longtail* keywords a DB-shaped site would actually rank
   pages for? A big-name domain ranking isn't disqualifying by itself --
   what matters is whether the result actually satisfies the search intent
   (a dedicated, DB-shaped page) or is incidental (a generic homepage, an
   unrelated blog post).
3. **Scoring & judgement.** Demand Score / Competition Score / DB Fit Score
   combine into a Priority Score; GO/HOLD/NO-GO follows spec rules that are
   all backed by thresholds in `config/viability.yaml` (never hardcoded).

This tool is built entirely on the existing DB Collector OS core: the same
SQLite file (`database.py`), the same migration mechanism
(`migrations/0002_viability.sql`), the same config-loading pattern
(`config.py` -> `viability/config.py`), the same CLI (`db-collector
viability ...` alongside `db-collector jobs ...`). No new crawler, HTTP
client, retry/rate-limit, or scheduler was introduced -- Phase 2 SERP data
comes in via CSV import, the same "initial version can be CSV import" the
spec explicitly allows, with an adapter architecture so a licensed API can
be swapped in later without touching scoring/judgement logic at all.

## Data model

All new tables hang off `db_ideas` (which theme) and, from
`keyword_metrics` onward, off `evaluation_runs` (which run / when). Nothing
is ever overwritten in place -- re-investigating a theme starts a new
`run_id`, so history is preserved for comparison (spec section 9).

```
db_ideas               -- one row per candidate DB theme
  evaluation_runs       -- one row per Phase 1/2 investigation pass
  keyword_candidates     -- the theme's structured keyword universe (axis-tagged)
    keyword_metrics        -- monthly search volume etc., per source, per run
    serp_queries            -- (run-scoped) queries actually issued for Phase 2
      serp_results             -- top-N results per query
    keyword_competition      -- (run-scoped) WEAK/MEDIUM/STRONG per keyword
  demand_summaries        -- (run-scoped) Phase 1 theme-level aggregation + PASS/FAIL
  db_idea_evaluations      -- (run-scoped) final scores + GO/HOLD/NO-GO + reasoning
```

## Search axes

`db_collector_os/viability/keyword_axes.py` defines the structured axis
model the spec calls for: `category` / `type` / `attribute` / `feature` /
`usage` / `pain_point` / `target` / `region` / `brand` / `motif` / `other`.
Not every theme uses every axis -- pass only the ones that apply.

## Walkthrough

```bash
db-collector viability idea create --theme "アクセサリーのオーダーメイド工房" --category handicraft
# -> idea_xxxxxxxx

cat > spec.yaml <<'EOF'
main_keywords: ["アクセサリー オーダーメイド"]
axes:
  type: ["指輪", "ネックレス"]
  motif: ["スカル", "クロス", "リリー"]
  region: ["東京", "埼玉"]
combos:
  - ["シルバーアクセサリー", "工房", "東京"]
EOF
db-collector viability keywords generate idea_xxxxxxxx --spec spec.yaml
db-collector viability keywords list idea_xxxxxxxx

# metrics.csv: keyword,monthly_search_volume[,competition,low_bid,high_bid,trend,source]
# -- exported from Google Keyword Planner or ラッコキーワード, or hand-typed
db-collector viability metrics import-csv idea_xxxxxxxx metrics.csv

db-collector viability phase1-run idea_xxxxxxxx
# -> {"run_id": "run_xxxx", "phase1_result": "PASS", ...} or FAIL (NO-GO, stops here)

# serp.csv: query,rank,title,url[,domain,snippet,site_type,page_type,
#           title_match,db_type_page,intent_satisfied,source]
# -- site_type/page_type/db_type_page/intent_satisfied are optional manual
#    (or LLM-assisted) judgement calls; left blank, a heuristic classifier
#    fills them in, but manual/LLM judgement of "does this page really
#    satisfy the search intent" is far more reliable than the heuristic.
db-collector viability serp import-csv run_xxxx idea_xxxxxxxx serp.csv
db-collector viability phase2-run run_xxxx

db-collector viability evaluate run_xxxx
db-collector viability report idea_xxxxxxxx          # human-readable text
db-collector viability report idea_xxxxxxxx --format json
db-collector viability runs-list idea_xxxxxxxx        # history across re-investigations
```

## Data sources: adapters, not hardcoded scraping

- `keyword_sources/csv_import.py` -- functional today.
- `keyword_sources/keyword_planner.py`, `keyword_sources/rakko.py` --
  stubs that fail closed (`NotConfiguredError`) with exact setup
  instructions. Google Keyword Planner needs a Google Ads developer token +
  OAuth credentials (human/ops task, paid Google Ads account); ラッコキーワード
  has no official public API, so its supported path stays manual CSV
  export, not scraping.
- `keyword_sources/gemini_supplement.py` -- optional LLM-based keyword
  *suggestion* (not volume data), defaults to a safe no-op.
- `serp_sources/csv_import.py` -- functional today (manually collected/
  exported SERP results).
- `serp_sources/serp_api.py` -- stub for a licensed SERP API (SerpApi.com,
  DataForSEO, Google Custom Search JSON API, ...); requires a paid API key
  a human must provision. Direct bulk scraping of Google Search is
  intentionally never implemented here.

Swapping a stub for a real integration only touches that one adapter file
-- `demand_analysis.py`, `competition_analysis.py`, `scoring.py`,
`judgement.py` and the CLI never need to change.

## Tuning thresholds and weights

Everything numeric lives in `config/viability.yaml` (or a file pointed to
by `DB_COLLECTOR_VIABILITY_CONFIG`): the Phase 1 demand gate, the Phase 2
site-type/page-type scoring weights, the Demand/Competition/DB
Fit/Priority score formulas, and the final GO/HOLD/NO-GO thresholds. None
of it is hardcoded in `db_collector_os/viability/*.py`.

## What still needs a human

- A Google Ads developer token + OAuth client (for real Keyword Planner
  data) -- paid Google Ads account, human-only setup.
- A licensed SERP API key (for automated Phase 2 collection) -- paid
  account, human-only setup.
- Anything from ラッコキーワード stays manual CSV export by policy (no
  official API to integrate against).

Until those exist, CSV import (optionally paired with manual/LLM judgement
calls recorded directly in the SERP CSV's override columns) is the
supported, spec-compliant way to run this tool.
