"""DB Viability Assessment Tool.

Given a candidate DB theme, decide GO / HOLD / NO-GO by checking, in order:

1. Phase 1 -- does real search demand exist (a single big keyword is not
   enough; longtail axis combinations are aggregated)?
2. Phase 2 -- for themes that pass Phase 1, is there SEO room to win on the
   longtail keywords a DB-shaped site would actually rank pages for?

Everything here sits on top of the existing DB Collector OS core (SQLite via
`database.py`, config loading via `config.py`, the same migration mechanism)
-- no new crawler, HTTP client, retry/rate-limit, or scheduler is
introduced. Data sources (keyword volume, SERP results) are adapter-based
(see `keyword_sources/` and `serp_sources/`) so CSV/manual import today can
be swapped for a real API later without touching the scoring/judgement
logic.
"""
