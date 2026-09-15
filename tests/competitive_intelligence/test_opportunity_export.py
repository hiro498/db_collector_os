from __future__ import annotations

import csv

from db_collector_os.competitive_intelligence.opportunity.exporter import export_all
from db_collector_os.competitive_intelligence.opportunity.repository import ComparisonRepository, ContentGapRepository
from db_collector_os.competitive_intelligence.repository.core import (
    CrawlRunRepository, CrawlUrlRepository, DomainRepository,
)
from db_collector_os.competitive_intelligence.repository.pages import PageRepository


def _seed_page(db, path="/a") -> tuple[str, str]:
    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(
        domain["domain_id"], "https://example.jp/", "affiliate_domain", "affiliate_domain", "general",
    )
    crawl_url_id, _ = CrawlUrlRepository(db).add(
        run_id, domain["domain_id"], f"https://example.jp{path}", f"https://example.jp{path}", discovered_by="seed",
    )
    page_id = PageRepository(db).upsert(
        crawl_url_id, run_id, domain["domain_id"], f"https://example.jp{path}", f"https://example.jp{path}",
        fetched_at="2026-01-01T00:00:00",
    )
    return page_id, run_id


def test_export_all_creates_three_files(db, tmp_path):
    page_id, run_id = _seed_page(db)
    from db_collector_os.competitive_intelligence.opportunity.repository import OpportunityRepository

    OpportunityRepository(db).upsert_analysis(
        "page", page_id, page_id, crawl_run_id=run_id, overall_opportunity_score=50.0, score_status="PARTIAL",
        confidence_label="MEDIUM", confidence_value=0.5, query="睡眠グッズ おすすめ",
    )
    paths = export_all(db, str(tmp_path))
    assert len(paths) == 3
    for p in paths:
        assert p and __import__("pathlib").Path(p).exists()


def test_export_opportunities_csv_content_and_encoding(db, tmp_path):
    page_id, run_id = _seed_page(db)
    from db_collector_os.competitive_intelligence.opportunity.repository import OpportunityRepository

    OpportunityRepository(db).upsert_analysis(
        "page", page_id, page_id, crawl_run_id=run_id, overall_opportunity_score=75.5, score_status="COMPLETE",
        confidence_label="HIGH", confidence_value=0.9, query="睡眠グッズ おすすめ", ai_opportunity_score=90.0,
    )
    paths = export_all(db, str(tmp_path))
    opp_csv = next(p for p in paths if p.endswith("opportunities.csv"))
    raw = open(opp_csv, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf"), "must use utf-8-sig so Japanese text doesn't mojibake in Excel"
    with open(opp_csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == list(rows[0])
    header = rows[0]
    row = dict(zip(header, rows[1]))
    assert row["keyword"] == "睡眠グッズ おすすめ"
    assert row["overall_score"] == "75.5"
    assert row["page_url"] == "https://example.jp/a"


def test_export_competitor_comparisons_csv(db, tmp_path):
    ComparisonRepository(db).upsert("page", "p1", "page", "p2", "organic_rank", 3.0, 10.0, -7.0, "left", "HIGH", "e")
    paths = export_all(db, str(tmp_path))
    comp_csv = next(p for p in paths if p.endswith("competitor_comparison.csv"))
    with open(comp_csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0][0] == "left_entity_type"
    assert "organic_rank" in rows[1]


def test_export_content_gaps_csv_joins_missing_lists(db, tmp_path):
    from db_collector_os.competitive_intelligence.opportunity.content_gap import ContentGapResult

    p1, _ = _seed_page(db, "/p1")
    p2, _ = _seed_page(db, "/p2")
    ContentGapRepository(db).upsert(
        p1, p2, ContentGapResult(["キーワードA", "キーワードB"], [], [], [], [], [], [], [], [], 40.0)
    )
    paths = export_all(db, str(tmp_path))
    gaps_csv = next(p for p in paths if p.endswith("content_gaps.csv"))
    with open(gaps_csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert "キーワードA; キーワードB" in rows[1]
