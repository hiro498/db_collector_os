"""Fingerprint computation used to detect exact duplicates cheaply.

A fingerprint is a hash of the strongest identifying signal available. We
prefer, in order: external_id, canonical_url, (normalized_name + domain).
Weaker signals (address/telephone alone) are handled by the matcher's fuzzy
path instead, since they are not reliable enough to hash-match directly.
"""

from __future__ import annotations

import hashlib


def _hash(*parts: str) -> str:
    joined = "|".join(p for p in parts if p)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def compute_fingerprint(
    entity_type: str,
    normalized_name: str | None = None,
    canonical_url: str | None = None,
    domain: str | None = None,
    external_id: str | None = None,
) -> str:
    if external_id:
        return _hash("external_id", entity_type, external_id)
    if canonical_url:
        return _hash("url", entity_type, canonical_url)
    if normalized_name and domain:
        return _hash("name_domain", entity_type, normalized_name, domain)
    if normalized_name:
        return _hash("name", entity_type, normalized_name)
    return ""
