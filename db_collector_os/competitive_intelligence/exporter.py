"""CSV export (spec section 43). Streams rows with csv.writer rather than
building giant strings in memory, and never HTML-renders these -- they are
meant to be opened in a spreadsheet.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..database import Database

_KEYWORDS_HEADER = (
    "domain", "keyword", "normalized_keyword", "score", "importance", "intent", "intent_group",
    "commercial_score", "branded_type", "modifier", "local", "prefecture", "city", "keyword_class",
    "page_count", "primary_page_count", "cluster",
)
_PAGE_KEYWORDS_HEADER = (
    "domain", "url", "title", "page_type", "keyword", "score", "importance", "intent",
    "commercial_score", "title_hit", "h1_hit", "h2_count", "body_count", "anchor_count", "rule_boost",
)
_PAGES_HEADER = (
    "url", "page_type", "page_type_confidence", "title", "primary_keyword", "score", "intent",
    "monetization_type", "monetization_score", "analysis_target", "updated_at_source",
)
_DOMAIN_SUMMARY_HEADER = (
    "domain", "target_type", "vertical", "status", "converged", "completion_rate",
    "discovered_total", "fetched_success", "analyzed_pages", "excluded_count", "unresolved_count",
    "total_keywords", "commercial_keyword_count", "started_at", "finished_at",
)
_CRAWL_AUDIT_HEADER = (
    "url", "normalized_url", "discovered_by", "source_url", "crawl_depth", "status",
    "exclusion_reason", "http_status", "redirect_to", "canonical_url", "is_canonical_duplicate",
    "indexable", "analysis_target", "fetch_attempts", "error_message",
)


def export_all(db: Database, crawl_run_id: str, out_dir: str) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = [
        export_domain_summary(db, crawl_run_id, out / "domain_summary.csv"),
        export_pages(db, crawl_run_id, out / "pages.csv"),
        export_keywords(db, crawl_run_id, out / "keywords.csv"),
        export_page_keywords(db, crawl_run_id, out / "page_keywords.csv"),
        export_crawl_audit(db, crawl_run_id, out / "crawl_audit.csv"),
    ]
    return [str(p) for p in paths]


def export_domain_summary(db: Database, crawl_run_id: str, path: Path) -> Path:
    run = db.query_one(
        "SELECT r.*, d.domain AS domain FROM ci_crawl_runs r JOIN ci_domains d ON d.domain_id = r.domain_id "
        "WHERE r.crawl_run_id=?",
        (crawl_run_id,),
    )
    profile = db.query_one("SELECT * FROM ci_site_profiles WHERE crawl_run_id=?", (crawl_run_id,)) if run else None
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(_DOMAIN_SUMMARY_HEADER)
        if run:
            writer.writerow([
                run["domain"], run["input_mode"], run["vertical"], run["status"], run["converged"],
                run["completion_rate"], run["discovered_total"], run["fetched_success"], run["analyzed_pages"],
                run["excluded_count"], run["unresolved_count"],
                profile["total_keywords"] if profile else 0,
                profile["commercial_keyword_count"] if profile else 0,
                run["started_at"], run["finished_at"],
            ])
    return path


def export_pages(db: Database, crawl_run_id: str, path: Path) -> Path:
    pages = db.query("SELECT * FROM ci_pages WHERE crawl_run_id=? ORDER BY page_type, url", (crawl_run_id,))
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(_PAGES_HEADER)
        for page in pages:
            primary = db.query_one(
                "SELECT k.keyword, pk.score, pk.intent FROM ci_page_keywords pk "
                "JOIN ci_keywords k ON k.keyword_id = pk.keyword_id "
                "WHERE pk.page_id=? AND pk.is_primary=1 LIMIT 1",
                (page["page_id"],),
            )
            writer.writerow([
                page["url"], page["page_type"], page["page_type_confidence"], page["title"],
                primary["keyword"] if primary else "", primary["score"] if primary else "",
                primary["intent"] if primary else "",
                page["monetization_type"], page["monetization_score"], page["analysis_target"],
                page["updated_at_source"],
            ])
    return path


def export_keywords(db: Database, crawl_run_id: str, path: Path) -> Path:
    run = db.query_one(
        "SELECT d.domain AS domain FROM ci_crawl_runs r JOIN ci_domains d ON d.domain_id = r.domain_id "
        "WHERE r.crawl_run_id=?",
        (crawl_run_id,),
    )
    domain = run["domain"] if run else ""
    rows = db.query(
        "SELECT k.*, "
        " (SELECT GROUP_CONCAT(DISTINCT modifier) FROM ci_keyword_modifiers m "
        "  JOIN ci_page_keywords pk2 ON pk2.page_keyword_id = m.page_keyword_id "
        "  WHERE pk2.keyword_id = k.keyword_id AND pk2.crawl_run_id=?) AS modifiers, "
        " MAX(pk.score) AS score, "
        " (SELECT importance FROM ci_page_keywords WHERE keyword_id=k.keyword_id AND crawl_run_id=? "
        "  ORDER BY score DESC LIMIT 1) AS importance, "
        " (SELECT intent FROM ci_page_keywords WHERE keyword_id=k.keyword_id AND crawl_run_id=? "
        "  ORDER BY score DESC LIMIT 1) AS intent, "
        " (SELECT intent_group FROM ci_page_keywords WHERE keyword_id=k.keyword_id AND crawl_run_id=? "
        "  ORDER BY score DESC LIMIT 1) AS intent_group, "
        " MAX(pk.commercial_score) AS commercial_score, "
        " COUNT(DISTINCT pk.page_id) AS page_count, SUM(pk.is_primary) AS primary_page_count, "
        " (SELECT c.label FROM ci_keyword_clusters c JOIN ci_keyword_cluster_members mm "
        "  ON mm.cluster_id = c.cluster_id WHERE mm.keyword_id = k.keyword_id AND c.crawl_run_id=?) AS cluster "
        "FROM ci_keywords k JOIN ci_page_keywords pk ON pk.keyword_id = k.keyword_id "
        "WHERE pk.crawl_run_id=? GROUP BY k.keyword_id ORDER BY score DESC",
        (crawl_run_id, crawl_run_id, crawl_run_id, crawl_run_id, crawl_run_id, crawl_run_id),
    )
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(_KEYWORDS_HEADER)
        for row in rows:
            writer.writerow([
                domain, row["keyword"], row["normalized_keyword"], row["score"], row["importance"],
                row["intent"], row["intent_group"], row["commercial_score"], row["branded_type"],
                row["modifiers"] or "", row["is_local"], row["prefecture"] or "", row["city"] or "",
                row["keyword_class"], row["page_count"], row["primary_page_count"] or 0, row["cluster"] or "",
            ])
    return path


def export_page_keywords(db: Database, crawl_run_id: str, path: Path) -> Path:
    run = db.query_one(
        "SELECT d.domain AS domain FROM ci_crawl_runs r JOIN ci_domains d ON d.domain_id = r.domain_id "
        "WHERE r.crawl_run_id=?",
        (crawl_run_id,),
    )
    domain = run["domain"] if run else ""
    rows = db.query(
        "SELECT pk.*, p.url AS page_url, p.title AS page_title, p.page_type AS page_type, k.keyword AS keyword "
        "FROM ci_page_keywords pk "
        "JOIN ci_pages p ON p.page_id = pk.page_id JOIN ci_keywords k ON k.keyword_id = pk.keyword_id "
        "WHERE pk.crawl_run_id=? ORDER BY p.url, pk.score DESC",
        (crawl_run_id,),
    )
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(_PAGE_KEYWORDS_HEADER)
        for row in rows:
            writer.writerow([
                domain, row["page_url"], row["page_title"], row["page_type"], row["keyword"], row["score"],
                row["importance"], row["intent"], row["commercial_score"], row["title_hit"], row["h1_hit"],
                row["h2_count"], row["body_count"], row["anchor_count"], row["rule_boost"],
            ])
    return path


def export_crawl_audit(db: Database, crawl_run_id: str, path: Path) -> Path:
    rows = db.query(
        "SELECT * FROM ci_crawl_urls WHERE crawl_run_id=? ORDER BY discovered_at", (crawl_run_id,)
    )
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CRAWL_AUDIT_HEADER)
        for row in rows:
            writer.writerow([
                row["url"], row["normalized_url"], row["discovered_by"], row["source_url"], row["crawl_depth"],
                row["status"], row["exclusion_reason"], row["http_status"], row["redirect_to"],
                row["canonical_url"], row["is_canonical_duplicate"], row["indexable"], row["analysis_target"],
                row["fetch_attempts"], row["error_message"],
            ])
    return path
