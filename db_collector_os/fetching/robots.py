"""robots.txt fetching + caching (in-process, per-run)."""

from __future__ import annotations

import urllib.robotparser
from urllib.parse import urlsplit

import requests


class RobotsCache:
    def __init__(self, user_agent: str, timeout: float = 10.0):
        self.user_agent = user_agent
        self.timeout = timeout
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _robots_url(self, url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}/robots.txt"

    def _get_parser(self, url: str) -> urllib.robotparser.RobotFileParser:
        robots_url = self._robots_url(url)
        if robots_url in self._cache:
            return self._cache[robots_url]

        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            resp = requests.get(robots_url, timeout=self.timeout, headers={"User-Agent": self.user_agent})
            if resp.status_code >= 400:
                parser.parse([])  # treat as "allow all" when robots.txt is absent
            else:
                parser.parse(resp.text.splitlines())
        except requests.RequestException:
            parser.parse([])  # fail open: an unreachable robots.txt does not halt collection
        self._cache[robots_url] = parser
        return parser

    def can_fetch(self, url: str) -> bool:
        try:
            parser = self._get_parser(url)
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def sitemaps(self, url: str) -> list[str]:
        try:
            parser = self._get_parser(url)
            return list(parser.site_maps() or [])
        except Exception:
            return []
