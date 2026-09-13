from __future__ import annotations

from db_collector_os.competitive_intelligence.keyword.candidate import generate_candidates
from db_collector_os.competitive_intelligence.keyword.tokenizer import (
    Morpheme,
    RegexFallbackTokenizer,
)


class FakeTokenizer:
    """Deterministic stand-in for SudachiTokenizer: fixed morpheme list,
    independent of dictionary version/segmentation differences."""

    def __init__(self, morphemes: list[Morpheme]):
        self._morphemes = morphemes

    def tokenize(self, text: str) -> list[Morpheme]:
        return self._morphemes


def _noun(surface: str) -> Morpheme:
    return Morpheme(surface=surface, normalized=surface, pos1="名詞")


def _particle(surface: str) -> Morpheme:
    return Morpheme(surface=surface, normalized=surface, pos1="助詞")


def test_generate_candidates_builds_1_to_5_word_windows_over_a_content_run():
    # "渋谷ラーメンおすすめランキング" -- 4 content nouns in a row, no particle break.
    tokenizer = FakeTokenizer([_noun("渋谷"), _noun("ラーメン"), _noun("おすすめ"), _noun("ランキング")])
    candidates = generate_candidates("渋谷ラーメンおすすめランキング", tokenizer)
    by_len = {}
    for c in candidates:
        by_len.setdefault(c.token_count, []).append(c.text)

    assert by_len[1] == ["渋谷", "ラーメン", "おすすめ", "ランキング"]
    assert "渋谷ラーメン" in by_len[2]
    assert "渋谷ラーメンおすすめ" in by_len[3]
    assert "渋谷ラーメンおすすめランキング" in by_len[4]
    assert 5 not in by_len  # only 4 content tokens exist -- no 5-word window possible


def test_generate_candidates_caps_at_max_ngram_five():
    tokenizer = FakeTokenizer([_noun(str(i)) for i in range(10)])
    candidates = generate_candidates("0123456789", tokenizer)
    assert max(c.token_count for c in candidates) == 5


def test_particles_break_a_content_run_into_separate_candidates():
    # "渋谷の美容室" -> "渋谷" | "の" (particle, breaks run) | "美容室"
    tokenizer = FakeTokenizer([_noun("渋谷"), _particle("の"), _noun("美容室")])
    candidates = generate_candidates("渋谷の美容室", tokenizer)
    texts = {c.text for c in candidates}
    assert "渋谷" in texts
    assert "美容室" in texts
    assert "渋谷美容室" not in texts  # never bridged across the particle


def test_candidate_count_is_linear_not_exponential_in_run_length():
    # 30 content tokens in one run: with max_len=5 this must stay O(n*5),
    # never explode toward 2**30 combinations.
    tokenizer = FakeTokenizer([_noun(f"w{i}") for i in range(30)])
    candidates = generate_candidates("x" * 30, tokenizer)
    assert len(candidates) < 30 * 5 + 5


def test_empty_text_yields_no_candidates():
    assert generate_candidates("", FakeTokenizer([])) == []


def test_regex_fallback_tokenizer_is_deterministic_without_sudachi():
    tokenizer = RegexFallbackTokenizer()
    morphemes = tokenizer.tokenize("渋谷ラーメン2024年")
    surfaces = [m.surface for m in morphemes]
    assert surfaces == ["渋谷", "ラーメン", "2024", "年"]
    assert all(m.is_content for m in morphemes)
