#!/usr/bin/env python3
"""Internal helper for scripts/phase1_batch1_goodsmile.sh: prints a full
Phase 1 batch report for one job as plain text (entity/evidence counts,
run_history, fetch_queue status + HTTP status breakdown, candidates,
review queue, checkpoint) plus two machine-parseable summary lines the
calling shell script uses to decide anomaly vs. success.

Not meant for interactive use -- `db-collector jobs show`/`queue`/`review`
already cover ad-hoc inspection; this exists so the batch watcher script
doesn't have to embed multi-line SQL inside nested bash/python quoting.
"""

from __future__ import annotations

import sys

from db_collector_os.checkpoint import CheckpointStore
from db_collector_os.config import load_config
from db_collector_os.database import Database


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: _phase1_batch1_report.py JOB_ID", file=sys.stderr)
        return 2
    job_id = sys.argv[1]

    cfg = load_config("config/default.yaml")
    db = Database(cfg.db_path)

    print("--- run_history (most recent 5) ---")
    for row in db.query(
        "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC LIMIT 5", (job_id,)
    ):
        print(dict(row))

    print()
    print("--- entity / evidence counts ---")
    n_entities = db.query_one(
        "SELECT COUNT(*) AS n FROM entities WHERE job_id=? AND deleted_at IS NULL", (job_id,)
    )["n"]
    n_evidence = db.query_one(
        "SELECT COUNT(*) AS n FROM evidence WHERE entity_id IN "
        "(SELECT entity_id FROM entities WHERE job_id=?)",
        (job_id,),
    )["n"]
    print(f"entity_count={n_entities}")
    print(f"evidence_count={n_evidence}")

    print()
    print("--- fetch_queue status breakdown ---")
    for row in db.query(
        "SELECT status, COUNT(*) AS n FROM fetch_queue WHERE job_id=? GROUP BY status", (job_id,)
    ):
        print(dict(row))

    print()
    print("--- fetch_queue HTTP status breakdown ---")
    for row in db.query(
        "SELECT last_http_status, COUNT(*) AS n FROM fetch_queue WHERE job_id=? GROUP BY last_http_status",
        (job_id,),
    ):
        print(dict(row))

    print()
    print("--- entity_candidates status breakdown ---")
    for row in db.query(
        "SELECT status, COUNT(*) AS n FROM entity_candidates WHERE job_id=? GROUP BY status", (job_id,)
    ):
        print(dict(row))

    print()
    print("--- review queue ---")
    n_open_review = db.query_one(
        "SELECT COUNT(*) AS n FROM review_queue WHERE job_id=? AND status='open'", (job_id,)
    )["n"]
    print(f"open_review_count={n_open_review}")
    for row in db.query(
        "SELECT review_id, reason, details FROM review_queue WHERE job_id=? AND status='open' LIMIT 20",
        (job_id,),
    ):
        print(dict(row))

    print()
    print("--- checkpoint ---")
    print(CheckpointStore(db).load(job_id))

    print()
    print("--- summary (machine-parsed by the calling shell script) ---")
    latest_run = db.query_one(
        "SELECT error_count, status AS run_status FROM run_history WHERE job_id=? "
        "ORDER BY started_at DESC LIMIT 1",
        (job_id,),
    )
    print(f"LATEST_RUN_ERROR_COUNT={latest_run['error_count'] if latest_run else -1}")
    print(f"LATEST_RUN_STATUS={latest_run['run_status'] if latest_run else 'none'}")
    print(f"OPEN_REVIEW_COUNT={n_open_review}")
    print(f"ENTITY_COUNT={n_entities}")

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
