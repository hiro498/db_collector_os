from __future__ import annotations

from db_collector_os.competitive_intelligence.enums import Importance
from db_collector_os.competitive_intelligence.keyword import scorer


def test_html_score_caps_at_40_and_does_not_double_count_a_single_position():
    # Section 21: "no infinite accumulation at the same position" -- passing
    # the same element_type twice (a set, so duplicates collapse) must not
    # change the score.
    assert scorer.compute_html_score({"title"}) == 15
    assert scorer.compute_html_score({"title", "title"}) == 15  # sets dedupe by construction
    huge = {"title", "h1", "url_slug", "breadcrumb", "category", "tag", "h2", "h3", "meta_description",
            "body", "anchor", "alt", "caption", "table", "faq", "cta", "button"}
    assert scorer.compute_html_score(huge) <= scorer.MAX_HTML_SCORE


def test_phrase_score_caps_at_15_and_scales_with_token_count():
    assert scorer.compute_phrase_score(1) == 0
    assert scorer.compute_phrase_score(2) == 4
    assert scorer.compute_phrase_score(3) == 8
    assert scorer.compute_phrase_score(5) == scorer.MAX_PHRASE_SCORE


def test_content_score_bounded_and_rewards_rarity_and_lead_position():
    common_word = scorer.compute_content_score(occurrences_in_body=1, doc_freq=10, total_docs=10, appears_in_lead=False)
    rare_word = scorer.compute_content_score(occurrences_in_body=1, doc_freq=1, total_docs=10, appears_in_lead=False)
    assert rare_word > common_word
    assert scorer.compute_content_score(occurrences_in_body=100, doc_freq=0, total_docs=10, appears_in_lead=True) <= scorer.MAX_CONTENT_SCORE


def test_site_structure_and_cross_page_scores_are_bounded():
    assert scorer.compute_site_structure_score(100) == scorer.MAX_SITE_STRUCTURE_SCORE
    assert scorer.compute_cross_page_score(100) == scorer.MAX_CROSS_PAGE_SCORE
    assert scorer.compute_cross_page_score(1) == 0


def test_score_breakdown_total_never_exceeds_100_even_with_extreme_inputs():
    breakdown = scorer.ScoreBreakdown(
        html_score=999, content_score=999, phrase_score=999, site_structure_score=999,
        intent_score=999, cross_page_score=999, rule_boost=999,
    )
    assert breakdown.total == 100


def test_score_breakdown_total_never_negative():
    breakdown = scorer.ScoreBreakdown(rule_boost=-999)
    assert breakdown.total == 0


def test_importance_bands_match_spec_section_24():
    assert Importance.from_score(100) == Importance.PRIMARY
    assert Importance.from_score(80) == Importance.PRIMARY
    assert Importance.from_score(79) == Importance.SECONDARY
    assert Importance.from_score(60) == Importance.SECONDARY
    assert Importance.from_score(59) == Importance.RELATED
    assert Importance.from_score(40) == Importance.RELATED
    assert Importance.from_score(39) == Importance.SUPPORTING
    assert Importance.from_score(20) == Importance.SUPPORTING
    assert Importance.from_score(19) == Importance.NOISE
    assert Importance.from_score(0) == Importance.NOISE


def test_rule_boost_promotes_importance_via_the_capped_total():
    # A keyword sitting right below a band boundary crosses it once
    # rule_boost is added -- this is how "Rule Boost may promote
    # Importance" (section 24) is satisfied without a separate override.
    low = scorer.ScoreBreakdown(html_score=18, phrase_score=0)
    assert low.importance == Importance.NOISE
    boosted = scorer.ScoreBreakdown(html_score=18, phrase_score=0, rule_boost=5)
    assert boosted.importance == Importance.SUPPORTING


def test_page_level_rule_boost_reasons_are_recorded():
    boost, reasons = scorer.compute_page_level_rule_boost(title_hit=True, h1_hit=True, h2_count=1, url_slug_hit=True)
    assert boost == scorer.RULE_BOOST_TITLE_H1_H2 + scorer.RULE_BOOST_TITLE_SLUG
    assert "title_h1_h2_cooccurrence" in reasons
    assert "title_slug_cooccurrence" in reasons


def test_page_level_rule_boost_zero_when_no_cooccurrence():
    boost, reasons = scorer.compute_page_level_rule_boost(title_hit=False, h1_hit=False, h2_count=0, url_slug_hit=False)
    assert boost == 0
    assert reasons == []
