"""Constants for the PHASE 15 Production Validation layer."""

from __future__ import annotations


class ValidationRunStatus:
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProductionValidationStatus:
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class AuditClass:
    """Machine-computed (`audit_class_auto`) or human-entered
    (`audit_class`) keyword-candidate quality grade (spec section 10) --
    the two are always stored in separate columns, never merged."""

    A = "A"  # obvious, strong acquisition keyword
    B = "B"  # reasonable related keyword
    C = "C"  # present in context but weak as an acquisition target
    D = "D"  # noise

    ALL = (A, B, C, D)
    ACQUISITION = (A, B)  # the "A+B" set the TOP50 KPI is computed over


class MoneyKeywordClass:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DemandStatus:
    OBSERVED = "OBSERVED"
    UNAVAILABLE = "UNAVAILABLE"


class BlueOceanCandidateStatus:
    OK = "OK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class KpiSource:
    """Distinguishes a KPI computed from real human-authored audit_class
    values (spec section 32) from the machine-only auto-quality proxy --
    the two must never be reported under the same label."""

    HUMAN_AUDITED = "HUMAN_AUDITED"
    AUTO_QUALITY_RATE = "AUTO_QUALITY_RATE"
