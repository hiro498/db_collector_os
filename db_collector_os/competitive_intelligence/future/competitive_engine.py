"""Competitive Engine -- NOT IMPLEMENTED in this P0.

Intended shape for P1: cross-domain comparison between two or more
`ci_domains` (Gap / reverse-Gap analysis over `ci_keywords` each domain
ranks/targets for). This P0 only analyzes one domain per crawl_run; nothing
in CORE compares across domains yet.
"""

from __future__ import annotations

from typing import Any


def compare_domains(domain_id_a: str, domain_id_b: str) -> dict[str, Any]:
    raise NotImplementedError(
        "Competitive Engine (cross-domain Gap/reverse-Gap analysis) is a "
        "P1+ extension point (spec section 46), not implemented in this P0."
    )
