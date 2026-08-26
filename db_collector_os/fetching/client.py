"""Fetch Engine: timeouts, UA, robots.txt, redirects, retry/backoff, and a
conservative SSRF guard. This module performs no destructive or evasive
tricks -- on a hard block (403/CAPTCHA-looking body) it surfaces that back to
the caller so the item can be routed to the review queue instead of retried
aggressively.
"""

from __future__ import annotations

import hashlib
import ipaddress
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from .robots import RobotsCache

_ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "application/xml", "text/xml", "application/json")

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "169.254.169.254"}

_CAPTCHA_MARKERS = ("captcha", "are you a human", "unusual traffic", "access denied")


class SSRFBlocked(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    ok: bool
    http_status: int | None = None
    final_url: str | None = None
    content: str | None = None
    content_type: str | None = None
    content_hash: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None
    retry_after: float | None = None
    blocked: bool = False  # captcha / hard-block -> caller should route to review


def _is_ssrf_risk(url: str, allow_private_networks: bool) -> bool:
    if allow_private_networks:
        return False
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return True
    host = (parts.hostname or "").lower()
    if not host or host in _BLOCKED_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    except ValueError:
        pass  # hostname, not a literal IP -- DNS-level SSRF is out of scope for this guard
    return False


class FetchEngine:
    def __init__(
        self,
        user_agent: str,
        timeout: float = 15.0,
        respect_robots: bool = True,
        allow_private_networks: bool = False,
        max_redirects: int = 5,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.allow_private_networks = allow_private_networks
        self.max_redirects = max_redirects
        self.robots = RobotsCache(user_agent=user_agent, timeout=timeout)
        self.session = requests.Session()

    def fetch(
        self, url: str, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult:
        if _is_ssrf_risk(url, self.allow_private_networks):
            return FetchResult(url=url, ok=False, error="blocked: unsafe target (SSRF guard)")

        if self.respect_robots and not self.robots.can_fetch(url):
            return FetchResult(url=url, ok=False, error="blocked by robots.txt")

        headers = {"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        try:
            resp = self.session.get(
                url, headers=headers, timeout=self.timeout,
                allow_redirects=True, stream=False,
            )
        except requests.exceptions.Timeout:
            return FetchResult(url=url, ok=False, error="timeout")
        except requests.exceptions.RequestException as exc:
            return FetchResult(url=url, ok=False, error=f"request error: {exc}")

        if len(resp.history) > self.max_redirects:
            return FetchResult(url=url, ok=False, error="too many redirects", http_status=resp.status_code)

        if resp.status_code == 304:
            return FetchResult(url=url, ok=True, http_status=304, final_url=resp.url)

        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            return FetchResult(url=url, ok=False, http_status=429, error="rate limited", retry_after=retry_after)

        if resp.status_code == 403:
            return FetchResult(url=url, ok=False, http_status=403, error="forbidden", blocked=True)

        if resp.status_code == 404:
            return FetchResult(url=url, ok=False, http_status=404, error="not found")

        if resp.status_code >= 500:
            return FetchResult(url=url, ok=False, http_status=resp.status_code, error="server error")

        content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type and not any(content_type.startswith(ct) for ct in _ALLOWED_CONTENT_TYPES):
            return FetchResult(
                url=url, ok=False, http_status=resp.status_code, content_type=content_type,
                error=f"unsupported content-type: {content_type}",
            )

        text = resp.text
        lowered = text[:5000].lower()
        if any(marker in lowered for marker in _CAPTCHA_MARKERS):
            return FetchResult(
                url=url, ok=False, http_status=resp.status_code, final_url=resp.url,
                error="captcha/block page detected", blocked=True,
            )

        content_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        return FetchResult(
            url=url, ok=True, http_status=resp.status_code, final_url=resp.url,
            content=text, content_type=content_type, content_hash=content_hash,
            etag=resp.headers.get("ETag"), last_modified=resp.headers.get("Last-Modified"),
        )


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone

            dt = parsedate_to_datetime(value)
            return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
        except Exception:
            return None
