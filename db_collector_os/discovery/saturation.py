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

    # discovered_total is the job's CUMULATIVE candidate count as of that
    # run (see candidates.total_count()), so a zero here means discovery
    # has NEVER found a single candidate across the job's whole history --
    # e.g. seed_urls only ever contained detail pages with nothing to
    # discover from, or a listing seed hadn't actually reached fetch_queue
    # yet (the exact production bug this guards against: min_entity_count=1
    # satisfied by one proof entity, combined with a trivial 0/0 -> 0.0
    # "rate" on every run, used to satisfy require_discovery_saturation
    # immediately even though no real discovery had ever run). That is
    # "never tried", not "tapered off" -- treat it as NOT saturated so
    # Phase 1 can't complete before discovery has had a genuine chance to
    # run at all.
    rates = []
    for run in runs:
        total = run["discovered_total"] or 0
        if total == 0:
            return False, "discovered_total is 0 -- discovery hasn't found anything yet, not saturated"
        new = run["new_candidates"] or 0
        rates.append(new / total)

    if all(r <= config.new_rate_threshold for r in rates):
        return True, f"last {len(rates)} runs all had new-discovery rate <= {config.new_rate_threshold}"
    return False, f"recent new-discovery rates: {[round(r, 3) for r in rates]}"
