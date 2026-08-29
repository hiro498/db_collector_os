"""api collector: JSON API sources (FANZA, DUGA, MGS, other product APIs).
One fetched response can enumerate many entities, so this overrides record
extraction to call the Adapter's `parse_api` instead of the HTML `extract`
path, and skips discovery-from-page (there is no HTML to link-follow).
"""

from __future__ import annotations

import json
from typing import Any

from ..adapters.base import Adapter, ExtractedRecord
from .pipeline import BaseCollector, RunOutcome


class ApiCollector(BaseCollector):
    def _extract_records(
        self, job: dict[str, Any], adapter: Adapter, url: str, content: str, content_type: str | None,
        outcome: RunOutcome,
    ) -> list[ExtractedRecord]:
        try:
            payload = json.loads(content) if content else {}
        except json.JSONDecodeError:
            return []
        try:
            return adapter.parse_api(payload, url)
        except NotImplementedError:
            return []
