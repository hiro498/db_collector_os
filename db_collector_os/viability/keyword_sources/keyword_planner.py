"""Google Keyword Planner adapter -- placeholder.

Real integration requires a Google Ads API developer token + OAuth client
credentials (a paid/approved Google Ads account is required to get a
developer token). None of that is available in this environment, so this
adapter intentionally fails closed with a clear, actionable error rather
than silently returning nothing (unlike NullKeywordSource) -- callers should
catch NotConfiguredError and fall back to CSV import, exactly as the CLI's
`keywords_planner` command does.

To wire this up for real once credentials exist:
  1. `pip install google-ads`
  2. Provide `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`,
     `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`,
     `GOOGLE_ADS_LOGIN_CUSTOMER_ID` as environment variables (never
     hardcode them).
  3. Implement `fetch()` using `GenerateKeywordIdeas` against those
     credentials, mapping the response into `KeywordMetricRecord`s.
This is user/ops setup, not something Claude Code can provision.
"""

from __future__ import annotations

import os

from .base import KeywordMetricRecord, NotConfiguredError

REQUIRED_ENV_VARS = (
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
)


class KeywordPlannerSource:
    name = "keyword_planner"

    def __init__(self):
        missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
        if missing:
            raise NotConfiguredError(
                "Google Keyword Planner adapter is not configured -- missing env var(s): "
                + ", ".join(missing)
                + ". Use keyword_sources.csv_import (CSV export from Keyword Planner) until "
                "these Google Ads API credentials are provisioned by a human operator."
            )

    def fetch(self, keywords: list[str]) -> list[KeywordMetricRecord]:
        raise NotImplementedError(
            "Google Ads API call not implemented yet -- see module docstring for the wiring steps."
        )
