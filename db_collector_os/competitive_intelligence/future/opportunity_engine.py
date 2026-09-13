"""Opportunity Engine -- NOT IMPLEMENTED in this P0.

Intended shape for P1: combine a keyword's `ci_page_keywords` score/intent
with (eventual) SERP-weakness signals from serp_engine to produce a
GO/HOLD/NO recommendation, persisted into `ci_opportunities`
(repository.future.OpportunityRepository). Requires serp_engine first.
"""

from __future__ import annotations

from typing import Any


def score_opportunity(keyword_id: str, crawl_run_id: str) -> dict[str, Any]:
    raise NotImplementedError(
        "Opportunity Engine is a P1+ extension point (spec section 46) and "
        "depends on serp_engine, which is also not implemented in this P0."
    )
