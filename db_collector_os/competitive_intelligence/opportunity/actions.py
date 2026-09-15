"""Action Recommendation engine (spec section 19). Codes and priorities
only -- no article/body text is generated anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from .content_gap import ContentGapResult
from .enums import ActionCode, ActionPriority, ReasonCode
from .reasons import Reason

_HIGH_PRIORITY_IMPACT = 70.0
_MEDIUM_PRIORITY_IMPACT = 40.0


@dataclass(frozen=True)
class Action:
    action_code: str
    priority: str
    reason_code: str | None
    target_page: str | None
    target_keyword: str | None


def _priority_for(impact_score: float) -> str:
    if impact_score >= _HIGH_PRIORITY_IMPACT:
        return ActionPriority.HIGH
    if impact_score >= _MEDIUM_PRIORITY_IMPACT:
        return ActionPriority.MEDIUM
    return ActionPriority.LOW


def generate_actions(
    reasons: list[Reason], content_gap: ContentGapResult | None, page_exists: bool,
    target_page: str | None, target_keyword: str | None,
) -> list[Action]:
    actions: list[Action] = []

    if content_gap is not None:
        if content_gap.missing_numeric_facts:
            actions.append(Action(ActionCode.ADD_NUMERIC_FACTS, _priority_for(content_gap.content_gap_score),
                                   ReasonCode.CONTENT_GAP, target_page, target_keyword))
        if content_gap.missing_comparison_dimensions:
            actions.append(Action(ActionCode.ADD_COMPARISON_DIMENSIONS, _priority_for(content_gap.content_gap_score),
                                   ReasonCode.CONTENT_GAP, target_page, target_keyword))
        if content_gap.missing_primary_information:
            actions.append(Action(ActionCode.ADD_PROPRIETARY_DATA, _priority_for(content_gap.content_gap_score),
                                   ReasonCode.CONTENT_GAP, target_page, target_keyword))
        if content_gap.missing_freshness_evidence:
            actions.append(Action(ActionCode.UPDATE_EVIDENCE, _priority_for(content_gap.content_gap_score),
                                   ReasonCode.CONTENT_GAP, target_page, target_keyword))
        if content_gap.missing_internal_link_topics:
            actions.append(Action(ActionCode.STRENGTHEN_INTERNAL_LINKS, _priority_for(content_gap.content_gap_score),
                                   ReasonCode.CONTENT_GAP, target_page, target_keyword))

    for reason in reasons:
        if reason.reason_code == ReasonCode.FANOUT_GAP:
            actions.append(Action(ActionCode.EXPAND_FANOUT_TOPIC, _priority_for(reason.impact_score),
                                   reason.reason_code, target_page, target_keyword))
        elif reason.reason_code == ReasonCode.COMMERCIAL_HIGH:
            actions.append(Action(ActionCode.TARGET_COMMERCIAL_QUERY, _priority_for(reason.impact_score),
                                   reason.reason_code, target_page, target_keyword))
        elif reason.reason_code == ReasonCode.MONETIZATION_HIGH:
            actions.append(Action(ActionCode.IMPROVE_CTA, _priority_for(reason.impact_score),
                                   reason.reason_code, target_page, target_keyword))
        elif reason.reason_code in (ReasonCode.HIGH_READINESS_NOT_CITED, ReasonCode.HIGH_RANK_NOT_CITED,
                                     ReasonCode.ORGANIC_AI_DIVERGENCE, ReasonCode.ORGANIC_GAP):
            code = ActionCode.IMPROVE_EXISTING_PAGE if page_exists else ActionCode.CREATE_NEW_PAGE
            actions.append(Action(code, _priority_for(reason.impact_score), reason.reason_code,
                                   target_page, target_keyword))

    # de-duplicate identical (action_code, reason_code) pairs, keeping the highest priority.
    priority_rank = {ActionPriority.HIGH: 3, ActionPriority.MEDIUM: 2, ActionPriority.LOW: 1}
    deduped: dict[tuple[str, str | None], Action] = {}
    for action in actions:
        key = (action.action_code, action.reason_code)
        existing = deduped.get(key)
        if existing is None or priority_rank[action.priority] > priority_rank[existing.priority]:
            deduped[key] = action
    return sorted(deduped.values(), key=lambda a: priority_rank[a.priority], reverse=True)
