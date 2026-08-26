"""Checkpoint / Resume: persist per-job progress so a killed worker or VPS
reboot resumes instead of restarting from scratch.
"""

from __future__ import annotations

import json
from typing import Any

from .database import Database
from .job_registry import now_iso


class CheckpointStore:
    def __init__(self, db: Database):
        self.db = db

    def save(self, job_id: str, run_id: str | None, phase: str | None, state: dict[str, Any]) -> None:
        self.db.execute(
            """INSERT INTO checkpoints (job_id, run_id, phase, state_json, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(job_id) DO UPDATE SET
                 run_id=excluded.run_id, phase=excluded.phase,
                 state_json=excluded.state_json, updated_at=excluded.updated_at""",
            (job_id, run_id, phase, json.dumps(state), now_iso()),
        )

    def load(self, job_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM checkpoints WHERE job_id = ?", (job_id,))
        if not row:
            return {"job_id": job_id, "run_id": None, "phase": None, "state": {}}
        return {
            "job_id": row["job_id"],
            "run_id": row["run_id"],
            "phase": row["phase"],
            "state": json.loads(row["state_json"] or "{}"),
        }

    def clear(self, job_id: str) -> None:
        self.db.execute("DELETE FROM checkpoints WHERE job_id = ?", (job_id,))

    def update_state(self, job_id: str, run_id: str | None, phase: str | None, **kv: Any) -> dict[str, Any]:
        current = self.load(job_id)["state"]
        current.update(kv)
        self.save(job_id, run_id, phase, current)
        return current
