"""Per-domain rate limiting state, persisted so it survives worker restarts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..database import Database
from ..job_registry import now_iso


class DomainRateLimiter:
    def __init__(self, db: Database):
        self.db = db

    def _get_or_create(self, domain: str, delay_seconds: float, concurrency: int) -> dict:
        row = self.db.query_one("SELECT * FROM domain_rate_limits WHERE domain=?", (domain,))
        if row:
            return row
        self.db.execute(
            "INSERT OR IGNORE INTO domain_rate_limits (domain, delay_seconds, concurrency, error_count) "
            "VALUES (?,?,?,0)",
            (domain, delay_seconds, concurrency),
        )
        return self.db.query_one("SELECT * FROM domain_rate_limits WHERE domain=?", (domain,))

    def is_allowed(self, domain: str, delay_seconds: float = 1.0, concurrency: int = 2) -> tuple[bool, float]:
        """Returns (allowed, seconds_to_wait_if_not)."""
        row = self._get_or_create(domain, delay_seconds, concurrency)
        now = datetime.now(timezone.utc)

        blocked_until = row.get("blocked_until")
        if blocked_until:
            bu = datetime.fromisoformat(blocked_until)
            if now < bu:
                return False, (bu - now).total_seconds()

        last = row.get("last_request_at")
        delay = row.get("delay_seconds") or delay_seconds
        if last:
            last_dt = datetime.fromisoformat(last)
            elapsed = (now - last_dt).total_seconds()
            if elapsed < delay:
                return False, delay - elapsed
        return True, 0.0

    def record_request(self, domain: str) -> None:
        self.db.execute(
            "UPDATE domain_rate_limits SET last_request_at=? WHERE domain=?",
            (now_iso(), domain),
        )

    def record_error(self, domain: str, block_seconds: float | None = None) -> None:
        self.db.execute(
            "UPDATE domain_rate_limits SET error_count = error_count + 1 WHERE domain=?",
            (domain,),
        )
        if block_seconds:
            blocked_until = (datetime.now(timezone.utc) + timedelta(seconds=block_seconds)).isoformat(
                timespec="seconds"
            )
            self.db.execute(
                "UPDATE domain_rate_limits SET blocked_until=? WHERE domain=?",
                (blocked_until, domain),
            )

    def record_success(self, domain: str) -> None:
        self.db.execute(
            "UPDATE domain_rate_limits SET error_count=0, blocked_until=NULL WHERE domain=?",
            (domain,),
        )
