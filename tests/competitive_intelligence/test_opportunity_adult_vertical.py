"""spec section 14: adult affiliate vertical comparison hook. No new schema
-- this reuses PHASE 1's existing generic ci_vertical_entities /
ci_vertical_entity_attributes tables, and no FANZA/DUGA/MGS connection
exists anywhere in this module (interface/schema/scoring hook only)."""
from __future__ import annotations

from db_collector_os.competitive_intelligence.opportunity.adult_vertical import (
    ATTRIBUTE_KEYS, compare_adult_entities,
)
from db_collector_os.competitive_intelligence.opportunity.repository import ComparisonRepository
from db_collector_os.database import new_id
from db_collector_os.job_registry import now_iso


def _seed_vertical_entity(db, name: str, attrs: dict[str, str]) -> str:
    vertical_id = db.query_one("SELECT vertical_id FROM ci_vertical_profiles WHERE name='adult_affiliate'")
    if not vertical_id:
        vid = new_id("vert_")
        db.execute(
            "INSERT INTO ci_vertical_profiles (vertical_id, name, description, created_at) VALUES (?,?,?,?)",
            (vid, "adult_affiliate", "test vertical", now_iso()),
        )
    else:
        vid = vertical_id["vertical_id"]
    entity_id = new_id("ventity_")
    db.execute(
        "INSERT INTO ci_vertical_entities (vertical_entity_id, vertical_id, name, entity_type, created_at) "
        "VALUES (?,?,?,?,?)",
        (entity_id, vid, name, "title", now_iso()),
    )
    for key, value in attrs.items():
        db.execute(
            "INSERT INTO ci_vertical_entity_attributes (vertical_entity_id, attr_key, attr_value) VALUES (?,?,?)",
            (entity_id, key, value),
        )
    return entity_id


def test_attribute_keys_match_spec_section_14():
    expected = {
        "actor", "actress", "title", "maker", "label", "series", "genre", "release_date", "duration",
        "review_count", "rating", "ranking", "genre_rank", "actress_rank", "maker_rank", "review_growth",
        "rating_delta", "exclusive_ratio", "new_release_ratio",
    }
    assert set(ATTRIBUTE_KEYS) == expected


def test_no_new_schema_added_for_adult_vertical(db):
    """Confirms the CORE/VERTICAL separation claim: no ci_adult_* tables
    exist -- everything routes through the pre-existing generic vertical
    tables from migration 0002."""
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any(t.startswith("ci_adult") for t in tables)
    assert "ci_vertical_entities" in tables
    assert "ci_vertical_entity_attributes" in tables


def test_compare_adult_entities_numeric_attributes(db):
    left = _seed_vertical_entity(db, "Title A", {"rating": "4.5", "review_count": "120", "ranking": "3"})
    right = _seed_vertical_entity(db, "Title B", {"rating": "4.2", "review_count": "300", "ranking": "1"})
    results = compare_adult_entities(db, left, right)
    dims = {r["dimension"]: r["winner"] for r in results}
    assert dims["rating"] == "left"       # 4.5 > 4.2, higher is better
    assert dims["review_count"] == "right"  # 300 > 120
    assert dims["ranking"] == "right"      # rank 1 beats rank 3 (lower is better)


def test_compare_adult_entities_skips_missing_attributes(db):
    left = _seed_vertical_entity(db, "Title A", {"rating": "4.5"})
    right = _seed_vertical_entity(db, "Title B", {})  # no attributes at all
    results = compare_adult_entities(db, left, right)
    assert results == [], "must never guess a comparison value for a missing attribute"


def test_compare_adult_entities_non_numeric_identity_fields_are_not_compared(db):
    left = _seed_vertical_entity(db, "Title A", {"maker": "MakerX", "rating": "4.0"})
    right = _seed_vertical_entity(db, "Title B", {"maker": "MakerY", "rating": "3.5"})
    results = compare_adult_entities(db, left, right)
    assert "maker" not in {r["dimension"] for r in results}
    assert "rating" in {r["dimension"] for r in results}


def test_compare_adult_entities_persists_via_generic_comparison_repository(db):
    left = _seed_vertical_entity(db, "Title A", {"rating": "4.5"})
    right = _seed_vertical_entity(db, "Title B", {"rating": "4.0"})
    compare_adult_entities(db, left, right)
    stored = ComparisonRepository(db).list_for_pair("vertical_entity", left, "vertical_entity", right)
    assert len(stored) == 1
    assert stored[0]["comparison_dimension"] == "rating"
