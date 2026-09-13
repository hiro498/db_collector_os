"""String constants used across the competitive_intelligence package.

Plain classes (not enum.Enum), matching db_collector_os.models.enums, so
values round-trip through SQLite TEXT columns and JSON without ceremony.
"""

from __future__ import annotations


class InputMode:
    AUTO = "auto"
    ADVERTISER_LP = "advertiser_lp"
    AFFILIATE_DOMAIN = "affiliate_domain"

    ALL = (AUTO, ADVERTISER_LP, AFFILIATE_DOMAIN)


class CrawlRunStatus:
    RUNNING = "running"
    STOPPED = "stopped"  # safe stop (stop_requested, or the iteration guard) -- resumable
    COMPLETED = "completed"
    FAILED = "failed"


class CrawlUrlStatus:
    """The resumable state machine from spec section 13. Only COMPLETED and
    EXCLUDED are terminal-and-not-retryable; every other status may be
    picked back up by CrawlEngine.resume()."""

    DISCOVERED = "discovered"
    QUEUED = "queued"
    FETCHING = "fetching"
    FETCHED = "fetched"
    PARSED = "parsed"
    CLASSIFIED = "classified"
    ANALYZED = "analyzed"
    COMPLETED = "completed"
    FAILED = "failed"
    EXCLUDED = "excluded"

    TERMINAL = (COMPLETED, EXCLUDED)
    PENDING = (DISCOVERED, QUEUED, FETCHING, FETCHED, PARSED, CLASSIFIED, ANALYZED)


class ExclusionReason:
    NON_HTML_ASSET = "non_html_asset"
    MAILTO = "mailto"
    TEL = "tel"
    JAVASCRIPT_URL = "javascript_url"
    EXTERNAL_DOMAIN = "external_domain"
    SUBDOMAIN = "subdomain"
    ADMIN_URL = "admin_url"
    ROBOTS_BLOCKED = "robots_blocked"
    CAPTCHA_BLOCKED = "captcha_blocked"
    CANONICAL_DUPLICATE = "canonical_duplicate"
    FETCH_FAILED = "fetch_failed"


class PageType:
    TOP = "top"
    ARTICLE = "article"
    RANKING = "ranking"
    COMPARISON = "comparison"
    REVIEW = "review"
    PRODUCT_SERVICE = "product_service"
    CATEGORY = "category"
    TAG = "tag"
    LP = "lp"
    COMPANY = "company"
    CONTACT = "contact"
    PRIVACY = "privacy"
    TERMS = "terms"
    LOGIN = "login"
    UTILITY = "utility"
    OTHER = "other"

    ALL = (TOP, ARTICLE, RANKING, COMPARISON, REVIEW, PRODUCT_SERVICE, CATEGORY, TAG, LP,
           COMPANY, CONTACT, PRIVACY, TERMS, LOGIN, UTILITY, OTHER)

    # Section 17: base KW-analysis inclusion/exclusion lists.
    ANALYSIS_INCLUDED = (TOP, ARTICLE, RANKING, COMPARISON, REVIEW, PRODUCT_SERVICE, CATEGORY, TAG, LP)
    ANALYSIS_EXCLUDED = (COMPANY, CONTACT, PRIVACY, TERMS, LOGIN, UTILITY)
    OTHER_INCLUSION_CONFIDENCE_MIN = 60


class Importance:
    PRIMARY = "primary"
    SECONDARY = "secondary"
    RELATED = "related"
    SUPPORTING = "supporting"
    NOISE = "noise"

    @staticmethod
    def from_score(score: int) -> str:
        if score >= 80:
            return Importance.PRIMARY
        if score >= 60:
            return Importance.SECONDARY
        if score >= 40:
            return Importance.RELATED
        if score >= 20:
            return Importance.SUPPORTING
        return Importance.NOISE


class Intent:
    INFORMATIONAL = "informational"
    COMMERCIAL_INVESTIGATION = "commercial_investigation"
    TRANSACTIONAL = "transactional"
    NAVIGATIONAL = "navigational"
    LOCAL = "local"


class IntentGroup:
    KNOW = "Know"
    DO = "Do"
    BUY = "Buy"
    GO = "Go"

    BY_INTENT = {
        Intent.INFORMATIONAL: KNOW,
        Intent.COMMERCIAL_INVESTIGATION: DO,
        Intent.TRANSACTIONAL: BUY,
        Intent.NAVIGATIONAL: GO,
        Intent.LOCAL: GO,
    }


class BrandedType:
    BRANDED = "branded"
    NON_BRANDED = "non_branded"
    MIXED = "mixed"


class KeywordClass:
    HEAD = "head"
    MIDDLE = "middle"
    LONG_TAIL = "long_tail"


class MonetizationType:
    INFORMATIONAL = "informational"
    COMMERCIAL = "commercial"
    MIXED = "mixed"
    UNKNOWN = "unknown"
