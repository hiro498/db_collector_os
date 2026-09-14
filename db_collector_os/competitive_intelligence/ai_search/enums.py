"""Constants for the AI Search Analysis module."""

from __future__ import annotations

EXTRACTOR_VERSION = "ai_search/1"


class NumericFactType:
    NUMERIC = "numeric"
    DERIVED = "derived"
    COMPARISON = "comparison"
    RATIO_PERCENTAGE = "ratio_percentage"
    RANKING = "ranking"
    SAMPLE_SIZE = "sample_size"


class ComparisonStructureType:
    TABLE = "table"
    LIST = "list"
    CARD = "card"
    HEADING = "heading"
    BODY = "body"


class FreshnessEventType:
    REVIEW_DELTA = "review_delta"
    RANKING_DELTA = "ranking_delta"
    PRICE_DELTA = "price_delta"
    INVENTORY_DELTA = "inventory_delta"
    NEW_ITEM_DELTA = "new_item_delta"
    BEFORE_AFTER_TEXT = "before_after_text"


class FanoutIntentClass:
    INFORMATIONAL = "informational"
    COMPARISON = "comparison"
    PRICE = "price"
    REVIEW = "review"
    RANKING = "ranking"
    BRAND = "brand"
    LOCAL = "local"
    HOWTO = "howto"
    PROBLEM_SOLVING = "problem_solving"

    ALL = (INFORMATIONAL, COMPARISON, PRICE, REVIEW, RANKING, BRAND, LOCAL, HOWTO, PROBLEM_SOLVING)


class CitationSurface:
    AIO = "aio"
    AI_MODE = "ai_mode"


# Sentinel used only in Python-side dicts/reports to render a NULL score
# distinctly from 0 -- never written to the DB (DB NULL is the real value).
UNAVAILABLE = "unavailable"
