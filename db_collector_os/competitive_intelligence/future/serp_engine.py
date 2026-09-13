"""SERP Engine -- NOT IMPLEMENTED in this P0.

Intended shape for P1: given a `ci_keywords` row, query a configured SERP
provider (none is wired up -- spec section 53 forbids introducing a paid
SERP API in this pass) and persist results into `ci_serp_queries` /
`ci_serp_results` (see repository.future.SerpRepository, which already
supports creating a query row with status='not_implemented').
"""

from __future__ import annotations

from typing import Any


def fetch_serp_results(keyword: str, provider: str | None = None) -> list[dict[str, Any]]:
    raise NotImplementedError(
        "SERP Engine is a P1+ extension point (spec section 46). "
        "No SERP provider is configured or called in this P0."
    )
