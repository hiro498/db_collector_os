"""Site-wide intent rollup (spec section 12): reuses each page's own
PHASE 1 `intent` label as-is (never re-classifies) and rolls the set of
labels seen for a keyword across pages into one primary + secondary set,
with a confidence derived from how much those per-page labels agree --
never a new probabilistic model.
"""

from __future__ import annotations

from collections import Counter


def rollup_intent(intents: list[str]) -> tuple[str | None, list[str], str]:
    """Returns (primary_intent, secondary_intents, intent_confidence)."""
    if not intents:
        return None, [], "LOW"
    counts = Counter(intents)
    primary, primary_count = counts.most_common(1)[0]
    secondary = sorted(i for i in counts if i != primary)
    agreement = primary_count / len(intents)
    if agreement >= 0.8 and len(intents) >= 2:
        confidence = "HIGH"
    elif agreement >= 0.5:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    return primary, secondary, confidence
