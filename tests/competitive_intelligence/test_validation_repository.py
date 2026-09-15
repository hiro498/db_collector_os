from __future__ import annotations

from db_collector_os.competitive_intelligence.validation.repository import (
    DomainKeywordSummaryRepository, TargetKeywordPriorityRepository, ValidationRunRepository,
)


def test_validation_run_create_and_get(db):
    repo = ValidationRunRepository(db)
    run_id = repo.create("https://example.jp/", 30, 1.0, "/tmp/out", None)
    row = repo.get(run_id)
    assert row["target_url"] == "https://example.jp/"
    assert row["status"] == "RUNNING"
    assert row["max_pages"] == 30


def test_validation_run_complete_persists_summary(db):
    repo = ValidationRunRepository(db)
    run_id = repo.create("https://example.jp/", 30, 1.0, None, None)
    repo.complete(run_id, "COMPLETED", "PASS", 0.9, False, {"keywords_total": 10})
    row = repo.get(run_id)
    assert row["status"] == "COMPLETED"
    assert row["production_validation_status"] == "PASS"
    assert row["top50_ab_rate"] == 0.9
    import json
    assert json.loads(row["summary_json"])["keywords_total"] == 10


def test_validation_run_list_recent_sorted_desc(db):
    repo = ValidationRunRepository(db)
    first = repo.create("https://a.example/", 30, 1.0, None, None)
    second = repo.create("https://b.example/", 30, 1.0, None, None)
    # started_at has 1-second resolution -- force distinct values so
    # DESC ordering is unambiguous, rather than depending on two calls
    # landing in different wall-clock seconds.
    db.execute("UPDATE ci_validation_runs SET started_at='2020-01-01T00:00:00' WHERE validation_run_id=?", (first,))
    db.execute("UPDATE ci_validation_runs SET started_at='2020-01-02T00:00:00' WHERE validation_run_id=?", (second,))
    rows = repo.list_recent()
    assert rows[0]["validation_run_id"] == second


def test_domain_keyword_summary_replace_all_is_idempotent(db):
    repo = ValidationRunRepository(db)
    run_id = repo.create("https://example.jp/", 30, 1.0, None, None)
    summary_repo = DomainKeywordSummaryRepository(db)
    row = dict(
        keyword="kw", normalized_keyword="kw", keyword_id=None, pages_count=1, page_types=["article"],
        best_keyword_score=50, avg_keyword_score=50.0, total_occurrences=1, title_occurrences=1,
        h1_occurrences=0, heading_occurrences=0, body_occurrences=0, anchor_occurrences=0,
        site_structure_score=0.0, cross_page_score=0.0,
    )
    summary_repo.replace_all(run_id, [row])
    summary_repo.replace_all(run_id, [row])
    rows = summary_repo.list_for_run(run_id)
    assert len(rows) == 1


def test_domain_keyword_summary_human_audit(db):
    repo = ValidationRunRepository(db)
    run_id = repo.create("https://example.jp/", 30, 1.0, None, None)
    summary_repo = DomainKeywordSummaryRepository(db)
    summary_repo.replace_all(run_id, [dict(
        keyword="kw", normalized_keyword="kw", keyword_id=None, pages_count=1, page_types=[],
        best_keyword_score=50, avg_keyword_score=50.0, total_occurrences=1, title_occurrences=1,
        h1_occurrences=0, heading_occurrences=0, body_occurrences=0, anchor_occurrences=0,
        site_structure_score=0.0, cross_page_score=0.0,
    )])
    ok = summary_repo.set_human_audit(run_id, "kw", "A", "looks great")
    assert ok is True
    row = summary_repo.get(run_id, "kw")
    assert row["audit_class"] == "A"
    assert row["audit_note"] == "looks great"

    missing = summary_repo.set_human_audit(run_id, "no-such-keyword", "A", None)
    assert missing is False


def test_target_keyword_priorities_replace_all_and_ranking_order(db):
    repo = ValidationRunRepository(db)
    run_id = repo.create("https://example.jp/", 30, 1.0, None, None)
    priority_repo = TargetKeywordPriorityRepository(db)
    priority_repo.replace_all(run_id, [
        dict(priority_rank=1, keyword="a", normalized_keyword="a"),
        dict(priority_rank=2, keyword="b", normalized_keyword="b"),
    ])
    rows = priority_repo.list_for_run(run_id)
    assert [r["keyword"] for r in rows] == ["a", "b"]

    priority_repo.replace_all(run_id, [dict(priority_rank=1, keyword="c", normalized_keyword="c")])
    rows2 = priority_repo.list_for_run(run_id)
    assert len(rows2) == 1
    assert rows2[0]["keyword"] == "c"
