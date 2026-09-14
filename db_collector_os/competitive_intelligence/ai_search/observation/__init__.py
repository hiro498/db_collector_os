"""PHASE 13: External SERP / AI Search Observation Layer.

Compares PHASE 12's internal, locally-computed
``ai_citation_readiness_score`` against real external observation --
organic SERP position, AI Overviews citation, AI Mode citation, and
fan-out subquery visibility. The two halves are never mixed:

- Internal readiness lives in ``ai_search.pipeline``/``ci_ai_page_analysis``
  (PHASE 12, unchanged by this package).
- External reality lives entirely in this package's new ``ci_*`` tables
  (migration 0005) and is rolled up per page into ``ci_ai_page_visibility``
  -- a physically separate table, not new columns bolted onto
  ``ci_ai_page_analysis``.

This environment (Claude Code on the web) cannot reach general external
sites -- confirmed in the PHASE 12 real-site smoke test (proxy 403 for
every host tried, not specific to any one target). Every provider in
``providers.py`` therefore returns ``ProviderStatus.UNAVAILABLE`` by
default rather than attempting a network call that is known to fail, and
``importer.py`` provides the primary way to get real observation data in:
offline JSON/CSV import from data gathered elsewhere (a VPS, a licensed
SERP API, a manual GSC export, ...). A network attempt that *does* fail
(403/blocked/proxy-denied) is reported as ``ProviderStatus.BLOCKED``, never
treated as an implementation defect and never silently scored as 0.
"""

from .pipeline import get_page_visibility, recompute_page_visibility

__all__ = ["recompute_page_visibility", "get_page_visibility"]
