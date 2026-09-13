"""Competitive Keyword / Content Discovery Engine.

Analyzes an advertiser LP or an affiliate site to recover the keyword
candidates a page (or a whole site) is targeting, with evidence.

Layout mirrors the CORE/VERTICAL split from the design brief:

- ``crawler`` / ``fetcher``   -- URL discovery, convergence crawling, fetch
- ``parser`` / ``page_classifier`` -- HTML structure extraction, page typing
- ``keyword``                 -- tokenization, candidate generation, scoring
- ``link_analyzer`` / ``monetization`` -- internal links, CTA/affiliate signals
- ``repository``              -- SQLite persistence (new `ci_*` tables only)
- ``service``                 -- orchestration used by both `cli` and `web`
- ``cli`` / ``web``           -- entry points
- ``vertical``                -- genre-specific extension point (empty CORE)
- ``future``                  -- explicitly unimplemented P1+ extension points

This package reuses the existing ``fetching``/``normalization``/``extraction``
modules rather than duplicating them, and only adds new (``ci_``-prefixed)
tables via ``migrations/0002_competitive_intelligence.sql``. It does not
modify any existing module, table, or CLI command.
"""
