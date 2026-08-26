"""Daily metrics aggregation, used by the Admin UI to show growth-per-day."""

from __future__ import annotations

from datetime import date
from typing import Any

from .database import Database


class MetricsStore:
    def __init__(self, db: Database):
        self.db = db

    def _today(self) -> str:
        return date.today().isoformat()

    def bump(self, **fields: int | float) -> None:
        """Increment today's daily_metrics row by the given field deltas."""
        today = self._today()
        self.db.execute(
            """INSERT INTO daily_metrics (date) VALUES (?)
               ON CONFLICT(date) DO NOTHING""",
            (today,),
        )
        for field, delta in fields.items():
            if field not in {
                "new_entities", "updated_entities", "fetch_success", "fetch_errors",
                "review_count", "jobs_executed", "runtime_seconds", "pages_fetched",
            }:
                continue
            self.db.execute(
                f"UPDATE daily_metrics SET {field} = {field} + ? WHERE date = ?",
                (delta, today),
            )

    def today(self) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM daily_metrics WHERE date = ?", (self._today(),))
        return row or {
            "date": self._today(), "new_entities": 0, "updated_entities": 0,
            "fetch_success": 0, "fetch_errors": 0, "review_count": 0,
            "jobs_executed": 0, "runtime_seconds": 0, "pages_fetched": 0,
        }

    def recent(self, days: int = 14) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM daily_metrics ORDER BY date DESC LIMIT ?", (days,)
        )
