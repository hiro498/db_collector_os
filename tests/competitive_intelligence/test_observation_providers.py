from __future__ import annotations

import responses

from db_collector_os.competitive_intelligence.ai_search.observation.enums import ProviderStatus
from db_collector_os.competitive_intelligence.ai_search.observation.providers import (
    HttpEndpointOrganicSerpProvider,
    NullAioObservationProvider,
    NullAiModeObservationProvider,
    NullFanoutObservationProvider,
    NullOrganicSerpProvider,
)


def test_null_providers_never_make_a_network_call_and_report_unavailable():
    for provider_cls in (
        NullOrganicSerpProvider, NullAioObservationProvider, NullAiModeObservationProvider,
        NullFanoutObservationProvider,
    ):
        provider = provider_cls()
        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            result = provider.fetch("query", "JP", "ja", "desktop")
        assert len(rsps.calls) == 0
        assert result.status == ProviderStatus.UNAVAILABLE
        assert result.error_message is None


def test_http_endpoint_provider_unavailable_when_no_endpoint_configured():
    provider = HttpEndpointOrganicSerpProvider(endpoint_template=None, user_agent="Test/1.0")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        result = provider.fetch("query", "JP", "ja", "desktop")
    assert len(rsps.calls) == 0
    assert result.status == ProviderStatus.UNAVAILABLE


def test_http_endpoint_provider_available_on_success():
    provider = HttpEndpointOrganicSerpProvider(
        endpoint_template="https://serp-provider.example/search?q={query}&country={country}", user_agent="Test/1.0",
    )
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://serp-provider.example/search", body="<html>results</html>",
                 status=200, content_type="text/html")
        result = provider.fetch("渋谷 ラーメン", "JP", "ja", "desktop")
    assert result.status == ProviderStatus.AVAILABLE
    assert result.response_hash is not None
    assert result.data["raw_html"] == "<html>results</html>"


def test_http_endpoint_provider_blocked_on_403():
    provider = HttpEndpointOrganicSerpProvider(
        endpoint_template="https://serp-provider.example/search?q={query}", user_agent="Test/1.0",
    )
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://serp-provider.example/search", status=403)
        result = provider.fetch("q", "JP", "ja", "desktop")
    assert result.status == ProviderStatus.BLOCKED
    assert result.raw_reference is not None


def test_http_endpoint_provider_blocked_on_429():
    provider = HttpEndpointOrganicSerpProvider(
        endpoint_template="https://serp-provider.example/search?q={query}", user_agent="Test/1.0",
    )
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://serp-provider.example/search", status=429)
        result = provider.fetch("q", "JP", "ja", "desktop")
    assert result.status == ProviderStatus.BLOCKED


def test_http_endpoint_provider_error_on_other_failure():
    provider = HttpEndpointOrganicSerpProvider(
        endpoint_template="https://serp-provider.example/search?q={query}", user_agent="Test/1.0",
    )
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://serp-provider.example/search", status=404)
        result = provider.fetch("q", "JP", "ja", "desktop")
    assert result.status == ProviderStatus.ERROR


def test_provider_never_sets_score_zero_on_failure():
    """spec section 4's core rule, checked directly against the dataclass
    shape: a ProviderResult carries no numeric score field at all -- a
    caller cannot accidentally read a fabricated 0."""
    provider = HttpEndpointOrganicSerpProvider(
        endpoint_template="https://serp-provider.example/search?q={query}", user_agent="Test/1.0",
    )
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://serp-provider.example/search", status=500)
        result = provider.fetch("q", "JP", "ja", "desktop")
    assert result.status == ProviderStatus.ERROR
    assert not hasattr(result, "score")
