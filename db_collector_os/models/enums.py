"""String enums used across job/queue/candidate/review status fields.

Plain str-based classes (not enum.Enum) so values round-trip through SQLite
TEXT columns and JSON without extra ceremony.
"""

from __future__ import annotations


class JobStatus:
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    REVIEW = "review"
    RETRY = "retry"
    FAILED = "failed"
    PAUSED = "paused"

    ALL = (IDLE, QUEUED, RUNNING, COMPLETED, REVIEW, RETRY, FAILED, PAUSED)


class JobPhase:
    BOOTSTRAP = "bootstrap"
    DISCOVERY = "discovery"
    COLLECT = "collect"
    VALIDATION = "validation"
    PHASE1_COMPLETE = "phase1_complete"
    INCREMENTAL = "incremental"

    ORDER = (BOOTSTRAP, DISCOVERY, COLLECT, VALIDATION, PHASE1_COMPLETE, INCREMENTAL)


class CollectorType:
    OFFICIAL_SITE = "official_site"
    LOCAL_BUSINESS = "local_business"
    PERSON = "person"
    API = "api"

    ALL = (OFFICIAL_SITE, LOCAL_BUSINESS, PERSON, API)


class CandidateStatus:
    NEW = "new"
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    REVIEW = "review"


class QueueStatus:
    QUEUED = "queued"
    FETCHING = "fetching"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class ReviewStatus:
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReviewReason:
    DUPLICATE_AMBIGUITY = "duplicate_ambiguity"
    CAPTCHA = "captcha"
    BLOCKED = "blocked"
    PARSE_FAILURE = "parse_failure"
    CONFLICTING_SOURCE = "conflicting_source"
    UNCERTAIN_ENTITY = "uncertain_entity"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    LOW_CONFIDENCE = "low_confidence"
    UNEXPECTED_SCHEMA = "unexpected_schema"
    ADAPTER_ERROR = "adapter_error"


class RunStatus:
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
