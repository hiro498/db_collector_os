from __future__ import annotations

import responses

from db_collector_os.fetching.client import FetchEngine


def _engine(**kwargs) -> FetchEngine:
    return FetchEngine(user_agent="TestBot/1.0", respect_robots=False, **kwargs)


@responses.activate
def test_fetch_success():
    responses.add(responses.GET, "https://example.com/a", body="<html>ok</html>", status=200, content_type="text/html")
    result = _engine().fetch("https://example.com/a")
    assert result.ok
    assert result.http_status == 200
    assert result.content_hash


@responses.activate
def test_fetch_404():
    responses.add(responses.GET, "https://example.com/missing", status=404)
    result = _engine().fetch("https://example.com/missing")
    assert not result.ok
    assert result.http_status == 404


@responses.activate
def test_fetch_403_is_blocked():
    responses.add(responses.GET, "https://example.com/forbidden", status=403)
    result = _engine().fetch("https://example.com/forbidden")
    assert not result.ok
    assert result.blocked is True


@responses.activate
def test_fetch_429_returns_retry_after():
    responses.add(responses.GET, "https://example.com/limited", status=429, headers={"Retry-After": "5"})
    result = _engine().fetch("https://example.com/limited")
    assert not result.ok
    assert result.http_status == 429
    assert result.retry_after == 5.0


@responses.activate
def test_fetch_5xx():
    responses.add(responses.GET, "https://example.com/broken", status=503)
    result = _engine().fetch("https://example.com/broken")
    assert not result.ok
    assert result.http_status == 503


@responses.activate
def test_fetch_conditional_not_modified():
    responses.add(responses.GET, "https://example.com/cached", status=304)
    result = _engine().fetch("https://example.com/cached", etag='"abc"')
    assert result.ok
    assert result.http_status == 304


@responses.activate
def test_fetch_unsupported_content_type_rejected():
    responses.add(responses.GET, "https://example.com/file.pdf", body=b"%PDF-1.4", status=200, content_type="application/pdf")
    result = _engine().fetch("https://example.com/file.pdf")
    assert not result.ok
    assert "content-type" in result.error


@responses.activate
def test_fetch_captcha_page_is_blocked():
    responses.add(
        responses.GET, "https://example.com/captcha", status=200, content_type="text/html",
        body="<html><body>Please complete the CAPTCHA to continue</body></html>",
    )
    result = _engine().fetch("https://example.com/captcha")
    assert not result.ok
    assert result.blocked is True


def test_ssrf_guard_blocks_private_ip():
    result = _engine().fetch("http://127.0.0.1/admin")
    assert not result.ok
    assert "SSRF" in result.error


def test_ssrf_guard_blocks_metadata_endpoint():
    result = _engine().fetch("http://169.254.169.254/latest/meta-data/")
    assert not result.ok


def test_ssrf_guard_allows_when_explicitly_enabled():
    result = _engine(allow_private_networks=True).fetch("http://127.0.0.1:1/should-just-fail-to-connect")
    # No SSRF block message; the (expected) connection failure is a different error.
    assert result.error != "blocked: unsafe target (SSRF guard)"
