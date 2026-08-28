#!/usr/bin/env python3
"""Internal helper for scripts/run_goodsmile_phase1_batch1.sh: prints a full
Phase 1 batch report for one job as plain text (entity/evidence counts,
run_history, fetch_queue status + HTTP status breakdown, candidates,
review queue, checkpoint) plus machine-parseable summary lines the calling
shell script uses to decide anomaly vs. success.

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
        "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 5", (job_id,)
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
    print("--- fetch_queue HTTP status breakdown (machine-parseable) ---")
    # Buckets on top of the raw per-code breakdown above, so the calling
    # watch script can gate on 403/404/429/5xx without parsing free-form
    # dict output. NULL/None (not yet fetched) and non-numeric statuses are
    # excluded from every bucket.
    http_counts = {"2xx": 0, "403": 0, "404": 0, "429": 0, "5xx": 0}
    for row in db.query(
        "SELECT last_http_status, COUNT(*) AS n FROM fetch_queue WHERE job_id=? "
        "AND last_http_status IS NOT NULL GROUP BY last_http_status",
        (job_id,),
    ):
        code = row["last_http_status"]
        n = row["n"]
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            continue
        if 200 <= code_int < 300:
            http_counts["2xx"] += n
        elif code_int == 403:
            http_counts["403"] += n
        elif code_int == 404:
            http_counts["404"] += n
        elif code_int == 429:
            http_counts["429"] += n
        elif 500 <= code_int < 600:
            http_counts["5xx"] += n
    print(f"HTTP_2XX_COUNT={http_counts['2xx']}")
    print(f"HTTP_403_COUNT={http_counts['403']}")
    print(f"HTTP_404_COUNT={http_counts['404']}")
    print(f"HTTP_429_COUNT={http_counts['429']}")
    print(f"HTTP_5XX_COUNT={http_counts['5xx']}")

    print()
    print("--- review queue ---")
    n_open_review = db.query_one(
        "SELECT COUNT(*) AS n FROM review_queue WHERE job_id=? AND status='open'", (job_id,)
    )["n"]
    print(f"open_review_count={n_open_review}")
    print("reason breakdown (open only):")
    for row in db.query(
        "SELECT reason, COUNT(*) AS n FROM review_queue WHERE job_id=? AND status='open' GROUP BY reason",
        (job_id,),
    ):
        print(dict(row))
    for row in db.query(
        "SELECT review_id, reason, details FROM review_queue WHERE job_id=? AND status='open' LIMIT 20",
        (job_id,),
    ):
        print(dict(row))

    print()
    print("--- checkpoint ---")
    checkpoint = CheckpointStore(db).load(job_id)
    print(checkpoint)
    checkpoint_row = db.query_one("SELECT updated_at FROM checkpoints WHERE job_id=?", (job_id,))
    print(f"checkpoint_updated_at={checkpoint_row['updated_at'] if checkpoint_row else None}")

    # -- historical totals (cumulative across EVERY run_history row this job -----
    # -- has ever had -- lifetime figures, NEVER used for the batch success --
    # -- gate; that must look only at the latest single execution, below). -----
    print()
    print("--- historical totals (sum of run_history across every run this job has had) ---")
    totals = db.query_one(
        "SELECT COALESCE(SUM(fetched_count),0) AS fetched, COALESCE(SUM(inserted_count),0) AS inserted, "
        "COALESCE(SUM(updated_count),0) AS updated, COALESCE(SUM(duplicate_count),0) AS duplicates, "
        "COALESCE(SUM(review_count),0) AS reviews, COALESCE(SUM(error_count),0) AS errors, "
        "COUNT(*) AS n_runs "
        "FROM run_history WHERE job_id=?",
        (job_id,),
    )
    print(f"HISTORICAL_FETCHED={totals['fetched']}")
    print(f"HISTORICAL_INSERTED={totals['inserted']}")
    print(f"HISTORICAL_UPDATED={totals['updated']}")
    print(f"HISTORICAL_DUPLICATES={totals['duplicates']}")
    print(f"HISTORICAL_REVIEWS={totals['reviews']}")
    print(f"HISTORICAL_ERRORS={totals['errors']}")
    print(f"HISTORICAL_RUN_COUNT={totals['n_runs']}")

    # -- latest execution only -- this, not the historical totals above, is ----
    # -- what the batch success/fail gate must evaluate: a run_history row is --
    # -- immutable once finalized, so exactly one row corresponds to "this ----
    # -- batch's execution" and its counts are never mixed with any other run.
    print()
    print("--- latest run (this execution only -- machine-parsed by the calling shell script) ---")
    latest_run = db.query_one(
        "SELECT run_id, status AS run_status, started_at, finished_at, discovered_count, "
        "fetched_count, inserted_count, updated_count, duplicate_count, review_count, error_count "
        "FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1",
        (job_id,),
    )
    print(f"LATEST_RUN_ID={latest_run['run_id'] if latest_run else 'none'}")
    print(f"LATEST_RUN_STATUS={latest_run['run_status'] if latest_run else 'none'}")
    print(f"LATEST_RUN_STARTED_AT={latest_run['started_at'] if latest_run else 'none'}")
    print(f"LATEST_RUN_FINISHED_AT={latest_run['finished_at'] if latest_run else 'none'}")
    print(f"LATEST_RUN_ERROR_COUNT={latest_run['error_count'] if latest_run else -1}")
    print(f"OPEN_REVIEW_COUNT={n_open_review}")
    print(f"ENTITY_COUNT={n_entities}")
    print(f"BATCH_DISCOVERED={latest_run['discovered_count'] if latest_run else 0}")
    print(f"BATCH_FETCHED={latest_run['fetched_count'] if latest_run else 0}")
    print(f"BATCH_INSERTED={latest_run['inserted_count'] if latest_run else 0}")
    print(f"BATCH_UPDATED={latest_run['updated_count'] if latest_run else 0}")
    print(f"BATCH_DUPLICATES={latest_run['duplicate_count'] if latest_run else 0}")
    print(f"BATCH_REVIEWS={latest_run['review_count'] if latest_run else 0}")
    print(f"BATCH_ERRORS={latest_run['error_count'] if latest_run else 0}")

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
