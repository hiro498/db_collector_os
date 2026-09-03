from __future__ import annotations

from db_collector_os.viability.store import ViabilityStore


def test_create_and_get_idea(db):
    store = ViabilityStore(db)
    idea_id = store.create_idea("テストテーマ", category="cat", notes="note")
    idea = store.get_idea(idea_id)
    assert idea["theme_name"] == "テストテーマ"
    assert idea["status"] == "new"


def test_add_keyword_candidate_is_idempotent_per_idea(db):
    store = ViabilityStore(db)
    idea_id = store.create_idea("テーマ")
    cid1, created1 = store.add_keyword_candidate(idea_id, "kw1", is_main=True)
    cid2, created2 = store.add_keyword_candidate(idea_id, "kw1", is_main=True)
    assert cid1 == cid2
    assert created1 is True
    assert created2 is False


def test_latest_metrics_for_idea_picks_most_recent_per_candidate(db):
    store = ViabilityStore(db)
    idea_id = store.create_idea("テーマ")
    cid, _ = store.add_keyword_candidate(idea_id, "kw1")
    store.add_keyword_metric(cid, source="csv_import", monthly_search_volume=10, collected_at="2024-01-01T00:00:00+00:00")
    store.add_keyword_metric(cid, source="csv_import", monthly_search_volume=99, collected_at="2024-06-01T00:00:00+00:00")

    rows = store.latest_metrics_for_idea(idea_id)
    assert len(rows) == 1
    assert rows[0]["monthly_search_volume"] == 99


def test_latest_metrics_for_idea_includes_candidates_with_no_metric_yet(db):
    store = ViabilityStore(db)
    idea_id = store.create_idea("テーマ")
    store.add_keyword_candidate(idea_id, "kw-no-metric")
    rows = store.latest_metrics_for_idea(idea_id)
    assert len(rows) == 1
    assert rows[0]["monthly_search_volume"] is None


def test_runs_are_not_overwritten_across_reinvestigation(db):
    store = ViabilityStore(db)
    idea_id = store.create_idea("テーマ")
    run1 = store.start_run(idea_id)
    store.finish_run(run1)
    run2 = store.start_run(idea_id)
    store.finish_run(run2)
    runs = store.list_runs(idea_id)
    assert {r["run_id"] for r in runs} == {run1, run2}
