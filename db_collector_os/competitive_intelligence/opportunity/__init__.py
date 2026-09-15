"""PHASE 14: Opportunity Score / Cross-Competitor Comparison.

Quantifies where a "win" is available across keywords/pages/domains by
combining PHASE 1 (keywords, monetization, internal links), PHASE 12
(AI Search Analysis evidence), and PHASE 13 (external observation /
Readiness-vs-Reality) into per-entity Opportunity analyses backed by
individual component scores, pairwise comparisons, content gaps, a Reason
Engine, and recommended actions -- never a single opaque number.
"""

from .pipeline import (
    compare_domains,
    compare_keywords,
    compare_pages,
    compute_keyword_opportunity,
    compute_page_opportunity,
    get_opportunity,
    get_opportunity_detail,
    recompute_all,
)

__all__ = [
    "compute_page_opportunity",
    "compute_keyword_opportunity",
    "compare_pages",
    "compare_domains",
    "compare_keywords",
    "get_opportunity",
    "get_opportunity_detail",
    "recompute_all",
]
