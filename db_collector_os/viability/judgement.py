"""Final GO / HOLD / NO-GO decision (spec section 7). Rule order:

1. Phase 1 failed -> NO-GO (never reaches here in practice -- runner.py
   short-circuits before Phase 2 -- but kept as a safety net if this is
   ever called directly).
2. Demand exists + longtail mostly WEAK -> GO (explicit spec shortcut).
3. Demand exists + longtail mostly STRONG -> NO-GO (explicit spec shortcut).
4. Otherwise, decide from priority_score against configurable thresholds
   (this is what naturally handles "需要大 + 一部競合が強いが攻略余地あり
   -> GO" and "判定困難 -> HOLD", since priority_score already blends
   demand, competition ease, and DB fit).
"""

from __future__ import annotations

from typing import Any

from .config import ViabilityConfig


def decide_final_judgement(
    phase1_result: str,
    competition_summary: dict[str, Any],
    demand_score: float,
    competition_score: float,
    db_fit_score: float,
    priority_score: float,
    config: ViabilityConfig,
) -> tuple[str, str]:
    fj = config.final_judgement

    if phase1_result != "PASS" and fj.get("no_go_if_phase1_fail", True):
        return "NO-GO", "Phase 1 で需要が確認できなかったため NO-GO。"

    weak_ratio = competition_summary.get("weak_ratio")
    strong_ratio = competition_summary.get("strong_ratio")

    go_weak_threshold = fj.get("go_if_weak_ratio_at_least", 0.55)
    if weak_ratio is not None and weak_ratio >= go_weak_threshold:
        return "GO", (
            f"需要あり、かつロングテールKWの {weak_ratio:.0%} がWEAK競合のため、"
            f"SEOロングテールで流入獲得余地がある -> GO。"
            f"(priority_score={priority_score})"
        )

    no_go_strong_threshold = fj.get("no_go_if_strong_ratio_at_least", 0.70)
    if strong_ratio is not None and strong_ratio >= no_go_strong_threshold:
        return "NO-GO", (
            f"需要はあるが、ロングテールKWの {strong_ratio:.0%} がSTRONG競合で攻略困難のため NO-GO。"
            f"(priority_score={priority_score})"
        )

    go_min = fj.get("go_priority_min", 55)
    hold_min = fj.get("hold_priority_min", 35)

    if priority_score >= go_min:
        judgement = "GO"
        reasoning = (
            f"priority_score={priority_score} が GO ライン ({go_min}) 以上。"
            f"demand={demand_score} / competition={competition_score} / db_fit={db_fit_score} の"
            f"バランスから、一部競合が強くても攻略余地ありと判断 -> GO。"
        )
    elif priority_score >= hold_min:
        judgement = "HOLD"
        reasoning = (
            f"priority_score={priority_score} は GO ライン ({go_min}) 未満・HOLD ライン ({hold_min}) 以上で"
            f"判定困難 -> HOLD (要確認)。"
        )
    else:
        judgement = "NO-GO"
        reasoning = (
            f"priority_score={priority_score} が HOLD ライン ({hold_min}) 未満のため NO-GO。"
        )

    return judgement, reasoning
