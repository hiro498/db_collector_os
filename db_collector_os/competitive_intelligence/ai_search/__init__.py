"""PHASE 12: AI Search Citation / Reference Analysis.

Decomposes "is this page likely to be cited by AI Overviews / AI Mode"
into objective, separately-stored signals rather than a single subjective
score. Two kinds of output exist side by side and must never be confused:

- Externally-dependent axes (Organic Visibility, AIO Citation, AI Mode
  Citation, Fan-out [SERP] Coverage, Source Preference/Brand Affinity) --
  this phase has no SERP/AIO/AI-Mode/Preferred-Sources access, so these
  are always persisted as NULL, never as 0 or a guessed value. See
  ``future/aio_observation.py`` and ``future/ai_mode_observation.py`` for
  the (currently NotImplementedError) adapters a later phase would wire up.
- Locally-computable signals (Proprietary/Primary Information, Numeric
  Facts, Comparison Information, Evidence Freshness, AIO Extractability,
  AI Mode content coverage, Fan-out *content* coverage, Source
  Transparency proxies) -- these are measured directly from crawled HTML
  and combined into ``ai_citation_readiness_score`` (0-100), which is
  explicitly a readiness/potential measure, never a claim of actual
  citation.

Every score is backed by stored evidence (``ci_ai_numeric_facts``,
``ci_ai_comparisons``, ``ci_ai_freshness_events``) -- see ``pipeline.py``.
"""

from .pipeline import analyze_ai_page, get_ai_analysis, recompute_ai_analysis

__all__ = ["analyze_ai_page", "recompute_ai_analysis", "get_ai_analysis"]
