from __future__ import annotations

from db_collector_os.competitive_intelligence.parser.boilerplate import detect_and_mark_boilerplate
from db_collector_os.competitive_intelligence.repository.core import (
    CrawlRunRepository,
    CrawlUrlRepository,
    DomainRepository,
)
from db_collector_os.competitive_intelligence.repository.pages import PageElementRepository, PageRepository


def _make_run(db):
    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(domain["domain_id"], "https://example.jp/", "affiliate_domain",
                                            "affiliate_domain", "general")
    return domain, run_id


def _make_page(db, domain, run_id, url, elements):
    crawl_url_id, _created = CrawlUrlRepository(db).add(run_id, domain["domain_id"], url, url, discovered_by="seed")
    page_id = PageRepository(db).upsert(crawl_url_id, run_id, domain["domain_id"], url, url,
                                         fetched_at="2024-01-01T00:00:00")
    PageElementRepository(db).replace_all(page_id, elements)
    return page_id


def test_nav_header_footer_always_marked_boilerplate(db):
    domain, run_id = _make_run(db)
    elements = [
        {"element_type": "nav", "text": "共通ナビ", "position": 0},
        {"element_type": "header", "text": "共通ヘッダー", "position": 1},
        {"element_type": "footer", "text": "共通フッター", "position": 2},
        {"element_type": "body", "text": "ページ固有の本文です。", "position": 3},
    ]
    page_id = _make_page(db, domain, run_id, "https://example.jp/a", elements)

    detect_and_mark_boilerplate(db, run_id)

    rows = PageElementRepository(db).list_for_page(page_id)
    by_type = {r["element_type"]: r["is_boilerplate"] for r in rows}
    assert by_type["nav"] == 1
    assert by_type["header"] == 1
    assert by_type["footer"] == 1
    assert by_type["body"] == 0


def test_repeated_body_text_across_many_pages_is_flagged_as_template_candidate(db):
    domain, run_id = _make_run(db)
    common_notice = "本サイトは広告を含みます。"
    for i in range(4):
        elements = [
            {"element_type": "body", "text": common_notice, "position": 0},
            {"element_type": "body", "text": f"ページ{i}固有の本文です。", "position": 1},
        ]
        _make_page(db, domain, run_id, f"https://example.jp/p{i}", elements)

    marked = detect_and_mark_boilerplate(db, run_id, min_pages=3, ratio_threshold=0.6)
    assert marked >= 4  # the shared notice across all 4 pages

    rows = db.query(
        "SELECT pe.text, pe.is_boilerplate FROM ci_page_elements pe JOIN ci_pages p ON p.page_id = pe.page_id "
        "WHERE p.crawl_run_id=?",
        (run_id,),
    )
    shared = [r for r in rows if r["text"] == common_notice]
    unique = [r for r in rows if r["text"] != common_notice]
    assert all(r["is_boilerplate"] == 1 for r in shared)
    assert all(r["is_boilerplate"] == 0 for r in unique)


def test_unique_content_is_never_marked_boilerplate_below_min_pages(db):
    domain, run_id = _make_run(db)
    _make_page(db, domain, run_id, "https://example.jp/a", [
        {"element_type": "body", "text": "同じ文章です。", "position": 0},
    ])
    _make_page(db, domain, run_id, "https://example.jp/b", [
        {"element_type": "body", "text": "同じ文章です。", "position": 0},
    ])
    # Only 2 pages total, below default min_pages=3 -- must not mark anything.
    marked = detect_and_mark_boilerplate(db, run_id)
    assert marked == 0
