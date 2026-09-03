"""Search-result API adapter -- placeholder.

Direct, unauthorized bulk scraping of Google Search is explicitly forbidden
for this project (see the task's rule 11 and README's compliance notes).
The supported way to automate Phase 2 result collection is a licensed SERP
API (e.g. SerpApi.com, DataForSEO, or Google's own Custom Search JSON API
for lighter volumes) -- any of those needs a paid account and API key
obtained by a human operator; none of that exists in this environment.

Until then, use serp_sources.csv_import.CsvSerpSource with a manually
collected/exported CSV. To wire a real provider in later:
  1. Provision the API key with the provider (human/ops task).
  2. Set `DB_COLLECTOR_SERP_API_KEY` (never hardcode it).
  3. Implement `search()` below to call that provider and map its response
     into `SerpResultRecord`s, then update `db_idea_evaluations`
     traceability (source column) accordingly -- no other module needs to
     change.
"""

from __future__ import annotations

import os

from .base import NotConfiguredError, SerpQueryResult

REQUIRED_ENV_VAR = "DB_COLLECTOR_SERP_API_KEY"


class SerpApiSource:
    name = "serp_api"

    def __init__(self):
        if not os.environ.get(REQUIRED_ENV_VAR):
            raise NotConfiguredError(
                f"SERP API adapter is not configured -- missing env var {REQUIRED_ENV_VAR}. "
                "Use serp_sources.csv_import (manually collected/exported SERP CSV) until a "
                "licensed SERP API key is provisioned by a human operator."
            )

    def search(self, query: str, max_results: int = 10) -> SerpQueryResult:
        raise NotImplementedError(
            "SERP API call not implemented yet -- see module docstring for the wiring steps."
        )
