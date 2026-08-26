"""Phase Management: bootstrap -> discovery -> collect -> validation ->
phase1_complete -> incremental, with configurable Phase-1-completion
conditions per job (config_json.phase1_conditions).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models.enums import JobPhase

DEFAULT_CONDITIONS = {
    "queue_empty": True,
    "min_entity_count": 0,
    "max_error_rate": 0.5,
    "max_unresolved_review": 10_000,
    "require_discovery_saturation": True,
    "consecutive_low_discovery_runs": 3,
}


@dataclass
class PhaseSignals:
    queue_empty: bool
    entity_count: int
    error_rate: float
    unresolved_review_count: int
    discovery_saturated: bool
    consecutive_low_discovery_runs: int


def next_phase(current_phase: str) -> str:
    order = JobPhase.ORDER
    if current_phase not in order:
        return JobPhase.BOOTSTRAP
    idx = order.index(current_phase)
    if idx + 1 >= len(order):
        return current_phase
    return order[idx + 1]


def phase1_conditions_met(signals: PhaseSignals, conditions: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    """Evaluate all configured Phase-1-completion conditions. Returns
    (met, list_of_unmet_reasons).
    """
    cfg = {**DEFAULT_CONDITIONS, **(conditions or {})}
    unmet = []

    if cfg.get("queue_empty") and not signals.queue_empty:
        unmet.append("fetch queue not empty")

    min_entities = cfg.get("min_entity_count", 0)
    if signals.entity_count < min_entities:
        unmet.append(f"entity_count {signals.entity_count} < min {min_entities}")

    max_error_rate = cfg.get("max_error_rate", 1.0)
    if signals.error_rate > max_error_rate:
        unmet.append(f"error_rate {signals.error_rate:.2f} > max {max_error_rate}")

    max_review = cfg.get("max_unresolved_review", 10_000)
    if signals.unresolved_review_count > max_review:
        unmet.append(f"unresolved_review_count {signals.unresolved_review_count} > max {max_review}")

    if cfg.get("require_discovery_saturation") and not signals.discovery_saturated:
        unmet.append("discovery not saturated yet")

    required_consecutive = cfg.get("consecutive_low_discovery_runs", 0)
    if required_consecutive and signals.consecutive_low_discovery_runs < required_consecutive:
        unmet.append(
            f"consecutive_low_discovery_runs {signals.consecutive_low_discovery_runs} < {required_consecutive}"
        )

    return (len(unmet) == 0), unmet
