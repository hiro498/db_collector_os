"""Constants for the observation layer."""

from __future__ import annotations


class ProviderStatus:
    """Every provider call returns exactly one of these -- spec section 4:
    "on failure to fetch, never set score = 0"."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"  # no data source configured; no network attempted
    BLOCKED = "blocked"          # a network attempt was made and refused/blocked
    ERROR = "error"              # a network attempt failed for an unrelated reason

    ALL = (AVAILABLE, UNAVAILABLE, BLOCKED, ERROR)


class ObservationType:
    ORGANIC = "organic"
    AIO = "aio"
    AI_MODE = "ai_mode"
    FANOUT = "fanout"
    GSC = "gsc"

    ALL = (ORGANIC, AIO, AI_MODE, FANOUT, GSC)


class Device:
    DESKTOP = "desktop"
    MOBILE = "mobile"

    ALL = (DESKTOP, MOBILE)


class ReadinessVsRealityClass:
    HIGH_READINESS_CITED = "A"
    HIGH_READINESS_NOT_CITED = "B"
    LOW_READINESS_CITED = "C"
    LOW_READINESS_NOT_CITED = "D"


class ResultType:
    ORGANIC = "organic"
    VIDEO = "video"
    IMAGE = "image"
    NEWS = "news"
    FORUM = "forum"
    SHOPPING = "shopping"
    OTHER = "other"
