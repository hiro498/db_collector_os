"""AI Overviews extractability (spec section 8). AIO tends to quote from
near the top of a page, so this only ever *adds* points when the lead
region (~first 100 content words) carries a direct answer/key fact/
comparison conclusion/summary. It never subtracts points for information
that lives further down the page -- position-based penalties are exactly
what spec section 8 forbids, and AI Mode (ai_mode.py) is scored on
coverage regardless of position for that same reason.
"""

from __future__ import annotations

from .numeric_facts import detect_numeric_facts
from .tokenizer_utils import lead_text

LEAD_WORD_COUNT = 100

_ANSWER_MARKERS = ("答えは", "結論は", "おすすめは", "一番のおすすめは", "正解は", "最もおすすめなのは")
_COMPARISON_CONCLUSION_MARKERS = ("一番人気は", "ベストな選択は", "最も評価が高いのは", "結論として")
_SUMMARY_MARKERS = ("まとめると", "結論から言うと", "要するに", "この記事のポイント", "本記事のポイント", "この記事では")


def compute_aio_signals(body_text: str) -> dict[str, object]:
    if not body_text:
        return {
            "lead_text": "", "answer_in_first_100_words": 0, "key_fact_in_first_100_words": 0,
            "comparison_result_near_top": 0, "summary_near_top": 0, "aio_extractability_score": 0,
        }
    lead = lead_text(body_text, LEAD_WORD_COUNT)
    key_fact = len(detect_numeric_facts(lead)) > 0
    answer = any(marker in lead for marker in _ANSWER_MARKERS)
    comparison_conclusion = any(marker in lead for marker in _COMPARISON_CONCLUSION_MARKERS)
    summary = any(marker in lead for marker in _SUMMARY_MARKERS)

    score = answer * 30 + key_fact * 25 + comparison_conclusion * 25 + summary * 20
    return {
        "lead_text": lead,
        "answer_in_first_100_words": int(answer),
        "key_fact_in_first_100_words": int(key_fact),
        "comparison_result_near_top": int(comparison_conclusion),
        "summary_near_top": int(summary),
        "aio_extractability_score": max(0, min(100, score)),
    }
