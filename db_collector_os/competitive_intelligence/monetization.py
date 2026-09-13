"""CTA / outbound-link classification and page monetization scoring
(spec sections 30-31). The ASP dictionary is deliberately generic (major
Japanese affiliate networks only) and easily extended -- CORE never
hardcodes a vertical-specific merchant list here (spec section 4/30).
"""

from __future__ import annotations

from typing import Any

from .enums import MonetizationType

# domain substring -> network name. Extend freely; this is a rule table,
# not a hardcoded genre assumption.
ASP_DOMAIN_NETWORKS: dict[str, str] = {
    "px.a8.net": "A8.net",
    "a8.net": "A8.net",
    "af.moshimo.com": "もしもアフィリエイト",
    "af.acefad.jp": "afb",
    "track.affiliate-b.com": "アフィリエイトB",
    "valuecommerce.com": "バリューコマース",
    "ck.jp.ap.valuecommerce.com": "バリューコマース",
    "hb.afl.rakuten.co.jp": "楽天アフィリエイト",
    "px.a.rakuten.co.jp": "楽天アフィリエイト",
    "amazon.co.jp": "Amazonアソシエイト",
    "amzn.to": "Amazonアソシエイト",
}
_SOCIAL_DOMAINS = (
    "twitter.com", "x.com", "instagram.com", "facebook.com", "youtube.com", "tiktok.com", "line.me",
)


def classify_outbound_link(target_domain: str) -> dict[str, str | None]:
    for pattern, network in ASP_DOMAIN_NETWORKS.items():
        if pattern in target_domain:
            return {"link_type": "affiliate", "affiliate_network": network, "merchant": None}
    if any(sd in target_domain for sd in _SOCIAL_DOMAINS):
        return {"link_type": "social", "affiliate_network": None, "merchant": None}
    return {"link_type": "other", "affiliate_network": None, "merchant": None}


def classify_cta_affiliate(target_domain: str | None) -> bool:
    if not target_domain:
        return False
    return any(pattern in target_domain for pattern in ASP_DOMAIN_NETWORKS)


def compute_monetization(
    cta_count: int, affiliate_link_count: int, has_comparison_table: bool, has_ranking: bool,
    avg_keyword_commercial_score: float,
) -> tuple[str, int]:
    score = (
        min(30, cta_count * 10) + min(40, affiliate_link_count * 15)
        + (20 if has_comparison_table else 0) + (10 if has_ranking else 0)
        + round(avg_keyword_commercial_score * 0.3)
    )
    score = max(0, min(100, score))
    if score >= 60:
        return MonetizationType.COMMERCIAL, score
    if score >= 25:
        return MonetizationType.MIXED, score
    return MonetizationType.INFORMATIONAL, score
