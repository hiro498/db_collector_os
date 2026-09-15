"""Constants for the PHASE 14 Opportunity Score layer."""

from __future__ import annotations


class Availability:
    """Every component score carries exactly one of these (spec section 2)
    -- a caller can never mistake "not observed" for "observed as zero"."""

    OBSERVED = "OBSERVED"        # a direct external measurement (SERP/AIO/AI-Mode/fanout/demand import)
    INFERRED = "INFERRED"        # a real computation over our own crawled content, not an external ground truth
    UNAVAILABLE = "UNAVAILABLE"  # neither exists -- value is always None when this is set

    ALL = (OBSERVED, INFERRED, UNAVAILABLE)


class ScoreStatus:
    COMPLETE = "COMPLETE"                # every component available
    PARTIAL = "PARTIAL"                  # some but not all components available
    INTERNAL_ONLY = "INTERNAL_ONLY"      # only INFERRED (internal) components available, zero OBSERVED ones
    NOT_ENOUGH_DATA = "NOT_ENOUGH_DATA"  # fewer than the minimum usable components available at all

    ALL = (COMPLETE, PARTIAL, INTERNAL_ONLY, NOT_ENOUGH_DATA)


class ConfidenceLabel:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    ALL = (HIGH, MEDIUM, LOW)


class ComparisonWinner:
    LEFT = "left"
    RIGHT = "right"
    TIE = "tie"
    UNKNOWN = "unknown"


class DivergenceClass:
    ORGANIC_STRONG_AI_WEAK = "organic_strong_ai_weak"
    ORGANIC_WEAK_AI_STRONG = "organic_weak_ai_strong"
    STRONG_BOTH = "strong_both"
    WEAK_BOTH = "weak_both"
    NOT_OBSERVED = "not_observed"


class ReasonCode:
    HIGH_READINESS_NOT_CITED = "HIGH_READINESS_NOT_CITED"
    HIGH_RANK_NOT_CITED = "HIGH_RANK_NOT_CITED"
    LOW_RANK_CITED = "LOW_RANK_CITED"
    COMPETITOR_WEAK_PROPRIETARY = "COMPETITOR_WEAK_PROPRIETARY"
    COMPETITOR_WEAK_FRESHNESS = "COMPETITOR_WEAK_FRESHNESS"
    COMPETITOR_WEAK_COMPARISON = "COMPETITOR_WEAK_COMPARISON"
    COMPETITOR_WEAK_NUMERIC_FACTS = "COMPETITOR_WEAK_NUMERIC_FACTS"
    FANOUT_GAP = "FANOUT_GAP"
    CONTENT_GAP = "CONTENT_GAP"
    COMMERCIAL_HIGH = "COMMERCIAL_HIGH"
    MONETIZATION_HIGH = "MONETIZATION_HIGH"
    OUR_CONTENT_STRONGER = "OUR_CONTENT_STRONGER"
    ORGANIC_AI_DIVERGENCE = "ORGANIC_AI_DIVERGENCE"
    ORGANIC_GAP = "ORGANIC_GAP"


class ActionCode:
    ADD_PROPRIETARY_DATA = "ADD_PROPRIETARY_DATA"
    ADD_COMPARISON_DIMENSIONS = "ADD_COMPARISON_DIMENSIONS"
    ADD_NUMERIC_FACTS = "ADD_NUMERIC_FACTS"
    UPDATE_EVIDENCE = "UPDATE_EVIDENCE"
    EXPAND_FANOUT_TOPIC = "EXPAND_FANOUT_TOPIC"
    STRENGTHEN_INTERNAL_LINKS = "STRENGTHEN_INTERNAL_LINKS"
    TARGET_COMMERCIAL_QUERY = "TARGET_COMMERCIAL_QUERY"
    IMPROVE_CTA = "IMPROVE_CTA"
    CREATE_NEW_PAGE = "CREATE_NEW_PAGE"
    IMPROVE_EXISTING_PAGE = "IMPROVE_EXISTING_PAGE"


class ActionPriority:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
