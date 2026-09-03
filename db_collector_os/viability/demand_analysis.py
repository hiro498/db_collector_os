"""Phase 1: aggregate a theme's keyword metrics and decide whether real
search demand exists at all. A single big keyword is never enough --
category x attribute x region x usage longtail volume is summed alongside
it (spec section 3).
"""

from __future__ import annotations

import statistics
from typing import Any

from .config import ViabilityConfig


def _dispersion(volumes: list[int]) -> float | None:
    """Coefficient of variation (stdev / mean) across keywords that have any
    volume at all. None when there's fewer than 2 data points or mean is 0.
    A higher value means demand is concentrated in a few keywords; a lower
    value means it's spread evenly across the longtail -- both are useful
    context for the human reading the final report, not a gate by itself.
    """
    if len(volumes) < 2:
        return None
    mean = statistics.mean(volumes)
    if mean == 0:
        return None
    return round(statistics.pstdev(volumes) / mean, 3)


def summarize_demand(
    keyword_rows: list[dict[str, Any]], config: ViabilityConfig, top_n: int = 10
) -> dict[str, Any]:
    """`keyword_rows` is ViabilityStore.latest_metrics_for_idea() output:
    each dict has keyword/is_main/monthly_search_volume (possibly None).
    Returns a summary dict ready for ViabilityStore.save_demand_summary(),
    plus a `reasoning` string a human can read directly.
    """
    gate = config.phase1_gate
    small_threshold = gate.get("small_volume_threshold", 10)

    main_rows = [r for r in keyword_rows if r.get("is_main")]
    longtail_rows = [r for r in keyword_rows if not r.get("is_main")]

    def vol(row: dict[str, Any]) -> int:
        return row.get("monthly_search_volume") or 0

    total_search_volume = sum(vol(r) for r in keyword_rows)
    main_kw_volume = sum(vol(r) for r in main_rows)
    kw_with_volume = [r for r in keyword_rows if vol(r) > small_threshold]
    kw_zero_or_low = [r for r in keyword_rows if vol(r) <= small_threshold]

    top_keywords = sorted(keyword_rows, key=vol, reverse=True)[:top_n]
    top_keywords_out = [{"keyword": r["keyword"], "monthly_search_volume": vol(r)} for r in top_keywords]

    dispersion = _dispersion([vol(r) for r in kw_with_volume]) if kw_with_volume else None

    summary = {
        "total_search_volume": total_search_volume,
        "main_kw_volume": main_kw_volume,
        "longtail_kw_count": len(longtail_rows),
        "kw_with_volume_count": len(kw_with_volume),
        "kw_zero_or_low_count": len(kw_zero_or_low),
        "dispersion": dispersion,
        "top_keywords": top_keywords_out,
    }

    reasons = []
    passed = True

    min_total = gate.get("min_total_search_volume", 300)
    if total_search_volume < min_total:
        passed = False
        reasons.append(f"総検索需要 {total_search_volume} が下限 {min_total} 未満")

    min_kw_with_volume = gate.get("min_kw_with_volume_count", 3)
    if len(kw_with_volume) < min_kw_with_volume:
        passed = False
        reasons.append(f"検索数ありKWが {len(kw_with_volume)} 件で下限 {min_kw_with_volume} 件未満")

    min_longtail = gate.get("min_longtail_kw_count", 3)
    if len(longtail_rows) < min_longtail:
        passed = False
        reasons.append(f"ロングテールKW数が {len(longtail_rows)} 件で下限 {min_longtail} 件未満")

    if passed:
        reasoning = (
            f"総検索需要 {total_search_volume}、検索数ありKW {len(kw_with_volume)} 件、"
            f"ロングテールKW {len(longtail_rows)} 件で最低ラインを満たすため、Phase 2 (競合調査) へ進めます。"
        )
    else:
        reasoning = "需要判定NG: " + "; ".join(reasons) + "。Phase 2には進めずNO-GOとします。"

    summary["phase1_result"] = "PASS" if passed else "FAIL"
    summary["reasoning"] = reasoning
    return summary
