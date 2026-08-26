"""Discovery Saturation: stops Phase 1 discovery from running forever.

If the last N discovery runs all had a new-candidate rate at or below a
threshold, discovery is considered saturated for that job.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..run_history import RunHistoryStore


@dataclass
class SaturationConfig:
    window_runs: int = 5
    new_rate_threshold: float = 0.05  # new_candidates / discovered_total
    min_runs_before_check: int = 3


def is_saturated(run_history: RunHistoryStore, job_id: str, config: SaturationConfig | None = None) -> tuple[bool, str]:
    config = config or SaturationConfig()
    runs = run_history.recent_discovery_runs(job_id, n=config.window_runs)
    if len(runs) < config.min_runs_before_check:
        return False, f"only {len(runs)} discovery runs so far (< {config.min_runs_before_check})"

    rates = []
    for run in runs:
        total = run["discovered_total"] or 0
        new = run["new_candidates"] or 0
        rate = (new / total) if total else 0.0
        rates.append(rate)

    if all(r <= config.new_rate_threshold for r in rates):
        return True, f"last {len(rates)} runs all had new-discovery rate <= {config.new_rate_threshold}"
    return False, f"recent new-discovery rates: {[round(r, 3) for r in rates]}"
