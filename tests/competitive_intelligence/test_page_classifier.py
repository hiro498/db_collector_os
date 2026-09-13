from __future__ import annotations

from db_collector_os.competitive_intelligence.enums import PageType
from db_collector_os.competitive_intelligence.page_classifier import classify, is_seo_analysis_target


def _elements(**by_type: str) -> list[dict]:
    return [{"element_type": t, "text": text, "position": i} for i, (t, text) in enumerate(by_type.items())]


def test_classify_top_page_by_root_path():
    page_type, confidence = classify([], [], "サイトTOP", "https://example.jp/")
    assert page_type == PageType.TOP
    assert confidence >= 30


def test_classify_company_page_by_url_and_text():
    elements = _elements(h1="会社概要")
    page_type, confidence = classify(elements, [], "会社概要", "https://example.jp/company/")
    assert page_type == PageType.COMPANY
    assert confidence >= 30


def test_classify_privacy_page():
    elements = _elements(h1="プライバシーポリシー")
    page_type, confidence = classify(elements, [], "プライバシーポリシー", "https://example.jp/privacy/")
    assert page_type == PageType.PRIVACY


def test_classify_ranking_page_from_title_keyword():
    elements = _elements(h1="渋谷ラーメンおすすめランキング2024")
    page_type, confidence = classify(elements, [], "渋谷ラーメンおすすめランキング2024", "https://example.jp/ramen-ranking/")
    assert page_type == PageType.RANKING


def test_classify_low_signal_page_reports_other_with_low_confidence_not_forced():
    page_type, confidence = classify([], [], None, "https://example.jp/xyz123/")
    assert page_type == PageType.OTHER
    assert confidence < 30


def test_classify_uses_schema_org_type_as_one_signal_among_several():
    # A single schema.org signal alone (+25) sits below the commit
    # threshold (30) by design -- classify() never lets one weak signal
    # force a high-confidence type. Paired with a corroborating text
    # signal, PRODUCT_SERVICE wins.
    json_ld = [{"@type": "Product"}]
    page_type, confidence = classify([], json_ld, "商品価格のご案内", "https://example.jp/products/1")
    assert page_type == PageType.PRODUCT_SERVICE
    assert confidence >= 30


def test_classify_single_schema_signal_alone_stays_below_commit_threshold():
    json_ld = [{"@type": "Product"}]
    page_type, confidence = classify([], json_ld, None, "https://example.jp/xyz123/")
    assert page_type == PageType.OTHER
    assert confidence == 25


def test_is_seo_analysis_target_includes_article_and_excludes_company():
    assert is_seo_analysis_target(PageType.ARTICLE, 80, indexable=True) is True
    assert is_seo_analysis_target(PageType.COMPANY, 80, indexable=True) is False
    assert is_seo_analysis_target(PageType.CONTACT, 90, indexable=True) is False


def test_is_seo_analysis_target_excludes_noindex_regardless_of_page_type():
    assert is_seo_analysis_target(PageType.ARTICLE, 90, indexable=False) is False


def test_is_seo_analysis_target_other_requires_high_confidence():
    assert is_seo_analysis_target(PageType.OTHER, 20, indexable=True) is False
    assert is_seo_analysis_target(PageType.OTHER, 80, indexable=True) is True
