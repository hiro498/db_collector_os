"""Observation Provider adapter architecture (spec sections 3-4).

Every provider -- organic SERP, AI Overviews, AI Mode, fan-out -- returns a
`ProviderResult` whose `status` is always one of `ProviderStatus`'s four
values (never a bare score). A provider that cannot get data returns
UNAVAILABLE or BLOCKED or ERROR; it never fabricates a result and never
lets the caller mistake "no data" for "observed and scored zero".

This module ships two provider families:

- `Null*Provider`: the default for every observation type. Makes no
  network call at all and always returns UNAVAILABLE -- correct today,
  since this environment cannot reach any general external site (the
  PHASE 12 real-site smoke test showed a blanket egress-proxy 403 for
  every host tried, not something specific to one target).
- `HttpEndpointOrganicSerpProvider`: a generic adapter for a *configured*
  HTTP endpoint (e.g. a licensed SERP API, or a VPS-side service the
  operator runs and controls). It contains no scraping logic and no
  knowledge of any specific search engine's page structure -- it reuses
  the existing FetchEngine as-is (robots.txt, SSRF guard, CAPTCHA
  detection unchanged) purely to probe availability, and returns the raw
  response for the caller to interpret. Parsing a specific provider's
  response format is intentionally out of scope here; wire that up
  alongside whichever real endpoint gets configured. With no endpoint
  configured (`endpoint_template=None`, the default), it never attempts a
  network call and returns UNAVAILABLE, identical to the Null providers.

Section 3's other listed future backends (VPS direct observation, GSC,
browser observation) are separate adapters that would implement the same
Protocols below -- see `gsc_adapter.py` for the GSC skeleton.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote

from ....fetching.client import FetchEngine
from ....job_registry import now_iso
from .enums import ProviderStatus


@dataclass
class ProviderResult:
    status: str
    provider: str
    observed_at: str = field(default_factory=now_iso)
    response_hash: str | None = None
    raw_reference: str | None = None
    error_message: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class OrganicSerpProvider(Protocol):
    name: str

    def fetch(self, query: str, country: str, language: str, device: str) -> ProviderResult: ...


class AioObservationProvider(Protocol):
    name: str

    def fetch(self, query: str, country: str, language: str, device: str) -> ProviderResult: ...


class AiModeObservationProvider(Protocol):
    name: str

    def fetch(self, query: str, country: str, language: str, device: str) -> ProviderResult: ...


class FanoutObservationProvider(Protocol):
    name: str

    def fetch(self, query: str, country: str, language: str, device: str) -> ProviderResult: ...


class _NullProviderBase:
    """Shared no-network implementation for every observation type."""

    name = "null"

    def fetch(self, query: str, country: str, language: str, device: str) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, provider=self.name)


class NullOrganicSerpProvider(_NullProviderBase):
    pass


class NullAioObservationProvider(_NullProviderBase):
    pass


class NullAiModeObservationProvider(_NullProviderBase):
    pass


class NullFanoutObservationProvider(_NullProviderBase):
    pass


class HttpEndpointOrganicSerpProvider:
    """Generic HTTP-endpoint organic-SERP probe. See module docstring --
    contains no search-engine-specific scraping logic. `endpoint_template`
    is a URL template with `{query}`/`{country}`/`{language}`/`{device}`
    placeholders for a *configured, operator-controlled* data source (a
    licensed SERP API, a VPS-side service); it is None by default, which
    keeps this provider's behavior identical to NullOrganicSerpProvider.
    """

    name = "http_endpoint"

    def __init__(self, endpoint_template: str | None, user_agent: str):
        self.endpoint_template = endpoint_template
        self._fetch_engine: FetchEngine | None = None
        if endpoint_template:
            self._fetch_engine = FetchEngine(user_agent=user_agent)

    def fetch(self, query: str, country: str, language: str, device: str) -> ProviderResult:
        if not self.endpoint_template or self._fetch_engine is None:
            return ProviderResult(status=ProviderStatus.UNAVAILABLE, provider=self.name)

        url = self.endpoint_template.format(
            query=quote(query), country=country, language=language, device=device,
        )
        result = self._fetch_engine.fetch(url)

        if result.blocked or result.http_status in (403, 429):
            return ProviderResult(
                status=ProviderStatus.BLOCKED, provider=self.name, raw_reference=url, error_message=result.error,
            )
        if not result.ok:
            return ProviderResult(
                status=ProviderStatus.ERROR, provider=self.name, raw_reference=url, error_message=result.error,
            )

        content = result.content or ""
        response_hash = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
        return ProviderResult(
            status=ProviderStatus.AVAILABLE, provider=self.name, raw_reference=url,
            response_hash=response_hash, data={"raw_html": content},
        )
