"""The structured search-axis model a DB theme's keyword universe is built
from. Not every axis applies to every theme -- callers only pass the axes
that make sense (see keyword_generator.generate_candidates).
"""

from __future__ import annotations

# Order here is also the priority order used when labeling a candidate whose
# axis_json has more than one key (see keyword_generator.primary_axis).
AXES: tuple[str, ...] = (
    "category",     # カテゴリ
    "type",         # 種類
    "attribute",    # 属性
    "feature",      # 特徴
    "usage",        # 用途
    "pain_point",   # 悩み
    "target",       # 対象者
    "region",       # 地域
    "brand",        # ブランド・メーカー
    "motif",        # モチーフ
    "other",        # その他テーマ固有属性
)


def validate_axes(axes: dict[str, list[str]]) -> None:
    unknown = sorted(set(axes) - set(AXES))
    if unknown:
        raise ValueError(f"unknown keyword axis/axes: {unknown} (valid: {AXES})")
