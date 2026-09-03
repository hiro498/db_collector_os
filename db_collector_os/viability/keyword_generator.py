"""Phase 1 keyword candidate generation: turn a theme's main keyword(s) +
per-axis value lists into a structured set of candidate search phrases, each
tagged with which axis/axes produced it -- so DB attributes and search
keywords stay linked (spec requirement: "DBに保存する属性と検索キーワードを
結び付けられる構造").

This is deliberately a simple, inspectable combination generator, not an NLP
keyword-suggestion engine -- real coverage still comes from
keyword_sources (CSV import from Keyword Planner / Rakko, or manual
research). The generator's job is to seed the initial candidate list and
guarantee every axis value produced at least one candidate to look up
metrics for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .keyword_axes import AXES, validate_axes


@dataclass
class KeywordCandidateSpec:
    keyword: str
    is_main: bool = False
    axis: dict[str, str] = field(default_factory=dict)


def generate_candidates(
    main_keywords: list[str],
    axes: dict[str, list[str]] | None = None,
    combos: list[list[str]] | None = None,
) -> list[KeywordCandidateSpec]:
    """Build the candidate list for a theme.

    - `main_keywords`: the theme's own big keyword(s), e.g. ["アクセサリー
      オーダーメイド"]. Always included as-is, tagged is_main=True.
    - `axes`: axis name -> list of values that apply to this theme (skip
      axes that don't apply -- not every theme has all of AXES). For each
      value, both `"{value} {main}"` and `"{main} {value}"` are generated
      (deduplicated) against every main keyword, tagged with that one axis.
    - `combos`: optional explicit multi-axis/multi-word phrases (e.g.
      ["シルバーアクセサリー", "工房", "東京"]) for hand-picked longtail
      combinations the simple pairwise generator wouldn't produce on its
      own. Stored space-joined, tagged axis={"combo": "<joined>"}.

    Returns a de-duplicated list (by keyword text) preserving first-seen
    order, main keywords first.
    """
    axes = axes or {}
    validate_axes(axes)
    combos = combos or []

    seen: set[str] = set()
    out: list[KeywordCandidateSpec] = []

    def add(keyword: str, is_main: bool, axis: dict[str, str]) -> None:
        keyword = " ".join(keyword.split())  # normalize whitespace
        if not keyword or keyword in seen:
            return
        seen.add(keyword)
        out.append(KeywordCandidateSpec(keyword=keyword, is_main=is_main, axis=axis))

    for main in main_keywords:
        add(main, is_main=True, axis={})

    for axis_name in AXES:
        for value in axes.get(axis_name, []):
            for main in main_keywords:
                add(f"{value} {main}", is_main=False, axis={axis_name: value})
                add(f"{main} {value}", is_main=False, axis={axis_name: value})

    for combo in combos:
        add(" ".join(combo), is_main=False, axis={"combo": " / ".join(combo)})

    return out
