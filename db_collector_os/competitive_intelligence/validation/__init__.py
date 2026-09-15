"""PHASE 15: Real-Data Production Validation / Target Keyword Discovery.

Integrates PHASE 3-14's existing engines end-to-end -- crawl, classify,
extract keywords, aggregate site-wide, integrate AI Citation Readiness,
external observation, and Opportunity Score -- into one Target Keyword
Priority ranking for a validated competitor domain. Introduces no new
analysis technique of its own; see pipeline.py's module docstring.
"""

from .pipeline import ValidationOptions, run_validation

__all__ = ["run_validation", "ValidationOptions"]
