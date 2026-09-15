"""Adult affiliate vertical comparison hook (spec section 14). CORE/VERTICAL
separation: this module adds no new schema at all -- it reuses PHASE 1's
already-existing generic `ci_vertical_entities` / `ci_vertical_entity_attributes`
tables (attr_key/attr_value pairs on a vertical_entity_id), which is exactly
the "interface / schema / scoring hook" the spec asks for without requiring
FANZA/DUGA/MGS DB connectivity in this phase. Populate those generic tables
(via a future adult-specific adapter, or an offline import) and this module
turns whatever attributes exist into the same generic
`ci_competitor_comparisons` rows every other entity type uses.
"""

from __future__ import annotations

from typing import Any

from ...database import Database
from .comparison import compare_dimension
from .enums import ConfidenceLabel
from .repository import ComparisonRepository

# spec section 14's candidate attributes. Purely a naming contract for
# `attr_key` values on ci_vertical_entity_attributes -- no table changes.
ATTRIBUTE_KEYS = (
    "actor", "actress", "title", "maker", "label", "series", "genre", "release_date", "duration",
    "review_count", "rating", "ranking", "genre_rank", "actress_rank", "maker_rank", "review_growth",
    "rating_delta", "exclusive_ratio", "new_release_ratio",
)

# Which of those attributes are numeric and therefore comparable via the
# generic higher-is-better comparator (section 7's shape). Non-numeric
# attributes (actor/title/maker/...) are identity fields, not comparison
# dimensions.
_NUMERIC_ATTRIBUTES = (
    "duration", "review_count", "rating", "ranking", "genre_rank", "actress_rank", "maker_rank",
    "review_growth", "rating_delta", "exclusive_ratio", "new_release_ratio",
)
_LOWER_IS_BETTER = {"ranking", "genre_rank", "actress_rank", "maker_rank"}


def _attributes(db: Database, vertical_entity_id: str) -> dict[str, str]:
    rows = db.query(
        "SELECT attr_key, attr_value FROM ci_vertical_entity_attributes WHERE vertical_entity_id=?",
        (vertical_entity_id,),
    )
    return {r["attr_key"]: r["attr_value"] for r in rows}


def compare_adult_entities(db: Database, left_vertical_entity_id: str, right_vertical_entity_id: str) -> list[dict[str, Any]]:
    """Compares two adult-affiliate vertical entities (e.g. two titles, or
    two actresses) attribute-by-attribute, storing each numeric dimension
    as an ordinary `ci_competitor_comparisons` row (entity_type='vertical_entity').
    Non-numeric or missing attributes are simply skipped -- never guessed.
    """
    left_attrs = _attributes(db, left_vertical_entity_id)
    right_attrs = _attributes(db, right_vertical_entity_id)
    repo = ComparisonRepository(db)
    results = []
    for key in _NUMERIC_ATTRIBUTES:
        left_raw, right_raw = left_attrs.get(key), right_attrs.get(key)
        if left_raw is None or right_raw is None:
            continue
        try:
            left_value, right_value = float(left_raw), float(right_raw)
        except (TypeError, ValueError):
            continue
        dimension = key if key not in _LOWER_IS_BETTER else f"{key}_asc"
        comparison = compare_dimension(
            "organic_rank" if key in _LOWER_IS_BETTER else "readiness", left_value, right_value,
            confidence=ConfidenceLabel.MEDIUM,
        )
        comparison_id = repo.upsert(
            "vertical_entity", left_vertical_entity_id, "vertical_entity", right_vertical_entity_id, key,
            comparison.left_value, comparison.right_value, comparison.gap_value, comparison.winner,
            comparison.confidence, f"attr_key={key}",
        )
        results.append({"comparison_id": comparison_id, "dimension": key, "winner": comparison.winner})
    return results
