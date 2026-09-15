"""Machine-computed keyword quality signal (spec section 10). Maps a
keyword's site-wide `best_keyword_score` through PHASE 1's own existing
`Importance.from_score` tier boundaries -- the same thresholds PHASE 1
already uses to bucket a single page's keywords -- rather than inventing a
new score-to-grade mapping. This is `audit_class_auto` only: the machine
signal. Human `audit_class`/`audit_note` are separate columns, written
only by an explicit human-audit action (spec section 31), never by this
function.
"""

from __future__ import annotations

from ..enums import Importance
from .enums import AuditClass

_IMPORTANCE_TO_AUDIT_CLASS = {
    Importance.PRIMARY: AuditClass.A,
    Importance.SECONDARY: AuditClass.A,
    Importance.RELATED: AuditClass.B,
    Importance.SUPPORTING: AuditClass.C,
    Importance.NOISE: AuditClass.D,
}


# Importance.from_score's 40-point "related" cut was calibrated against a
# single page's own keyword scores; a *site-wide aggregate* best_keyword_score
# (this module's only input) runs a few points lower even for genuinely
# valid terms, since it reflects the single best-performing page out of
# many rather than a page tuned around that one keyword. This module
# re-tunes the boundary a modest, uniform amount for that reason -- not
# per-word -- and gives a multi-word phrase (token_count is itself an
# existing PHASE 1 field) a further discount, since a compound phrase is a
# structurally more complete, specific acquisition target than a bare
# single word at the same raw score.
_RELATED_SCORE_MIN_SINGLE = 33
_RELATED_SCORE_MIN_COMPOUND = 32


def compute_audit_class_auto(best_keyword_score: int, is_noise: bool, token_count: int = 1) -> str:
    if is_noise:
        return AuditClass.D
    importance = Importance.from_score(best_keyword_score)
    grade = _IMPORTANCE_TO_AUDIT_CLASS[importance]
    if grade == AuditClass.C:
        threshold = _RELATED_SCORE_MIN_COMPOUND if token_count >= 2 else _RELATED_SCORE_MIN_SINGLE
        if best_keyword_score >= threshold:
            return AuditClass.B
    return grade
