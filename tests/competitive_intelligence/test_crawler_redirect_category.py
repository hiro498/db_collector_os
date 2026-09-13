"""Dedicated coverage for redirect-following and category-page crawling
(spec section 6: affiliate_domain crawling must cover category/tag pages
and redirect targets, not just sitemap-listed URLs).
"""

from __future__ import annotations

import responses

from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.enums import PageType
from db_collector_os.competitive_intelligence.repository.core import CrawlRunRepository, CrawlUrlRepository
from db_collector_os.competitive_intelligence.repository.pages import PageRepository

_ROOT_HTML = """<!doctype html><html><head><title>Redirect Test Site</title></head><body>
<main>
<a href="/category/ramen/">ラーメンカテゴリ</a>
<a href="/old-article/">古い記事URL</a>
</main>
</body></html>"""

_CATEGORY_HTML = """<!doctype html><html><head><title>ラーメンカテゴリ一覧</title></head><body>
<main><h1>ラーメンカテゴリ一覧</h1>
<a href="/new-article/">渋谷ラーメンおすすめ記事</a>
</main>
</body></html>"""

_NEW_ARTICLE_HTML = """<!doctype html><html><head>
<title>渋谷ラーメンおすすめ記事</title>
<link rel="canonical" href="https://redir.example.jp/new-article/">
</head><body>
<main><h1>渋谷ラーメンおすすめ記事</h1>
<p>渋谷には数多くのラーメン店が存在しますが、その中でも特におすすめできるお店を今回は詳しくご紹介していきます。
実際に足を運んで食べ比べた結果をもとに、味・価格・雰囲気の観点からまとめました。</p>
<p>まず最初にご紹介するのは駅から徒歩5分の場所にあるお店で、地元の常連客からも長年愛され続けている名店です。
スープのコクと麺の食感のバランスが絶妙で、初めて訪れる方にも自信を持っておすすめできます。</p>
<p>続いてご紹介するお店は、比較的新しくオープンしたばかりですが、すでに行列ができるほどの人気を集めています。
渋谷でラーメンを探している方は、ぜひ今回ご紹介したお店を参考にしてみてください。</p>
</main>
</body></html>"""


def _mock_redirect_site():
    responses.add(responses.GET, "https://redir.example.jp/robots.txt", status=404)
    responses.add(responses.GET, "https://redir.example.jp/sitemap.xml", status=404)
    responses.add(responses.GET, "https://redir.example.jp/", body=_ROOT_HTML, content_type="text/html")
    responses.add(responses.GET, "https://redir.example.jp/category/ramen/", body=_CATEGORY_HTML,
                  content_type="text/html")
    responses.add(
        responses.GET, "https://redir.example.jp/old-article/", status=302,
        headers={"Location": "https://redir.example.jp/new-article/"},
    )
    responses.add(responses.GET, "https://redir.example.jp/new-article/", body=_NEW_ARTICLE_HTML,
                  content_type="text/html")


@responses.activate
def test_category_page_is_crawled_and_classified(db):
    _mock_redirect_site()
    engine = CrawlEngine(db, user_agent="TestBot/1.0")
    run_id = engine.start_affiliate_domain("https://redir.example.jp/", requested_mode="affiliate_domain")

    urls = CrawlUrlRepository(db).list_all(run_id, limit=100)
    category_url = next(u for u in urls if u["url"] == "https://redir.example.jp/category/ramen/")
    assert category_url["status"] == "completed"

    pages = {p["url"]: p for p in PageRepository(db).list_for_run(run_id, limit=100)}
    assert pages["https://redir.example.jp/category/ramen/"]["page_type"] == PageType.CATEGORY


@responses.activate
def test_redirect_is_followed_and_recorded_on_the_source_url(db):
    _mock_redirect_site()
    engine = CrawlEngine(db, user_agent="TestBot/1.0")
    run_id = engine.start_affiliate_domain("https://redir.example.jp/", requested_mode="affiliate_domain")

    crawl_url_repo = CrawlUrlRepository(db)
    old_url = crawl_url_repo.get_by_normalized(run_id, "https://redir.example.jp/old-article")
    assert old_url is not None
    assert old_url["status"] == "completed"
    assert old_url["http_status"] == 200  # final response status after following the redirect
    assert old_url["redirect_to"] == "https://redir.example.jp/new-article/"

    # The redirect source served /new-article/'s HTML, whose canonical
    # self-references /new-article/ -- normalize_url(canonical) differs
    # from /old-article's own normalized_url, so it is correctly flagged
    # as a canonical duplicate rather than double-counted as its own page.
    assert old_url["is_canonical_duplicate"] == 1
    assert old_url["analysis_target"] == 0

    new_url = crawl_url_repo.get_by_normalized(run_id, "https://redir.example.jp/new-article")
    assert new_url is not None
    assert new_url["is_canonical_duplicate"] == 0
    assert new_url["analysis_target"] == 1


@responses.activate
def test_run_converges_and_completes_with_redirect_and_category_in_scope(db):
    _mock_redirect_site()
    engine = CrawlEngine(db, user_agent="TestBot/1.0")
    run_id = engine.start_affiliate_domain("https://redir.example.jp/", requested_mode="affiliate_domain")
    run = CrawlRunRepository(db).get(run_id)
    assert run["status"] == "completed"
    assert run["converged"] == 1
    assert run["unresolved_count"] == 0
