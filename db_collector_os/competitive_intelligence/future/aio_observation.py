"""AI Overviews citation observation -- NOT IMPLEMENTED in this P0/PHASE 12.

Intended shape for a later phase: query Google AI Overviews for a keyword,
detect whether a given page is cited, and persist the result into
`ci_ai_citation_observations` (surface='aio') / the aio_* summary columns
on `ci_ai_page_analysis`. No such query is made anywhere in this codebase;
`ai_search.pipeline` always leaves those columns NULL (see spec section 13
-- "no dummy citations").
"""

from __future__ import annotations

from typing import Any


def observe_aio_citation(page_id: str, keyword: str) -> dict[str, Any]:
    raise NotImplementedError(
        "AIO citation observation is a future-phase extension point (spec section 13). "
        "No AI Overviews access exists in this codebase."
    )
