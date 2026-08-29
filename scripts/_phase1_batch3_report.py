#!/usr/bin/env python3
"""Internal helper for scripts/run_goodsmile_phase1_batch3.sh: prints the
full Phase 1 batch #3 report for one job -- everything batch #2's report
prints, plus the fields specific to proving the run-lifecycle fix actually
worked in production: RUN_COUNT (how many run_history rows THIS batch
created), FETCHED_TOTAL/INSERTED_TOTAL/UPDATED_TOTAL/ERROR_TOTAL (this
batch's own aggregate, not the job's lifetime historical totals), and
LIFECYCLE_OK (did this batch avoid the "one URL = one run" pathology, and
never leave the job showing status=retry for a run that actually
succeeded).

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
    if len(sys.argv) not in (2, 3, 4):
        print("usage: _phase1_batch3_report.py JOB_ID [ENTITY_COUNT_BEFORE] [RUN_COUNT_BEFORE]", file=sys.stderr)
        return 2
    job_id = sys.argv[1]
    entity_count_before = int(sys.argv[2]) if len(sys.argv) >= 3 and sys.argv[2].isdigit() else None
    run_count_before = int(sys.argv[3]) if len(sys.argv) >= 4 and sys.argv[3].isdigit() else None

    cfg = load_config("config/default.yaml")
    db = Database(cfg.db_path)

    print("--- run_history (most recent 5) ---")
    for row in db.query(
        "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 5", (job_id,)
    ):
        print(dict(row))

    print()
    print("--- job / seed config ---")
    job = db.query_one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
    import json as _json
    config_json = _json.loads(job["config_json"] or "{}") if job else {}
    seed_urls = config_json.get("seed_urls", [])
    job_status_snapshot = job["status"] if job else "none"
    print(f"JOB_ID={job_id}")
    print(f"STATUS={job_status_snapshot}")
    print(f"PHASE={job['phase'] if job else 'none'}")
    print(f"ENABLED={bool(job['enabled']) if job else False}")
    print(f"SEED_URL_COUNT={len(seed_urls)}")
    # Snapshot BEFORE the watcher's own post-batch jobs disable/pause calls
    # overwrite status -- this is what the job's status actually was when
    # this run settled, which is what LIFECYCLE_OK needs to judge.
    print(f"JOB_STATUS_AT_REPORT_TIME={job_status_snapshot}")

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
    print(f"EVIDENCE_COUNT={n_evidence}")
    print(f"ENTITY_COUNT_AFTER={n_entities}")
    if entity_count_before is not None:
        print(f"ENTITY_COUNT_BEFORE={entity_count_before}")
        print(f"ENTITY_DELTA={n_entities - entity_count_before}")
    else:
        print("ENTITY_COUNT_BEFORE=unknown")
        print("ENTITY_DELTA=unknown")

    print()
    print("--- discovery: entity_candidates ---")
    n_candidates = db.query_one(
        "SELECT COUNT(*) AS n FROM entity_candidates WHERE job_id=?", (job_id,)
    )["n"]
    print(f"DISCOVERED_URL_COUNT={n_candidates}")
    for row in db.query(
        "SELECT status, COUNT(*) AS n FROM entity_candidates WHERE job_id=? GROUP BY status", (job_id,)
    ):
        print(dict(row))

    print()
    print("--- fetch_queue status breakdown ---")
    queue_by_status: dict[str, int] = {}
    for row in db.query(
        "SELECT status, COUNT(*) AS n FROM fetch_queue WHERE job_id=? GROUP BY status", (job_id,)
    ):
        print(dict(row))
        queue_by_status[row["status"]] = row["n"]
    queue_total = db.query_one("SELECT COUNT(*) AS n FROM fetch_queue WHERE job_id=?", (job_id,))["n"]
    print(f"QUEUE_TOTAL={queue_total}")
    print(f"QUEUE_PENDING={queue_by_status.get('queued', 0)}")
    print(f"QUEUE_FETCHED={queue_by_status.get('done', 0)}")
    print(f"QUEUE_FAILED={queue_by_status.get('failed', 0)}")

    print()
    print("--- fetch_queue HTTP status breakdown ---")
    for row in db.query(
        "SELECT last_http_status, COUNT(*) AS n FROM fetch_queue WHERE job_id=? GROUP BY last_http_status",
        (job_id,),
    ):
        print(dict(row))

    print()
    print("--- fetch_queue HTTP status breakdown (machine-parseable) ---")
    http_counts = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "403": 0, "404": 0, "429": 0}
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
        elif 300 <= code_int < 400:
            http_counts["3xx"] += n
        elif 400 <= code_int < 500:
            http_counts["4xx"] += n
            if code_int == 403:
                http_counts["403"] += n
            elif code_int == 404:
                http_counts["404"] += n
            elif code_int == 429:
                http_counts["429"] += n
        elif 500 <= code_int < 600:
            http_counts["5xx"] += n
    print(f"HTTP_2XX={http_counts['2xx']}")
    print(f"HTTP_3XX={http_counts['3xx']}")
    print(f"HTTP_4XX={http_counts['4xx']}")
    print(f"HTTP_5XX={http_counts['5xx']}")
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
    print(f"REVIEW_OPEN={n_open_review}")
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
    print(f"CHECKPOINT_PHASE={checkpoint.get('phase')}")
    print(f"CHECKPOINT_STATE={checkpoint.get('state')}")
    checkpoint_row = db.query_one("SELECT updated_at FROM checkpoints WHERE job_id=?", (job_id,))
    checkpoint_updated_at = checkpoint_row["updated_at"] if checkpoint_row else None
    print(f"checkpoint_updated_at={checkpoint_updated_at}")
    print(f"CHECKPOINT={checkpoint.get('phase')}|{checkpoint.get('state')}|updated_at={checkpoint_updated_at}")

    # -- historical totals (cumulative across EVERY run_history row this job -----
    # -- has ever had -- lifetime figures, NEVER used for the batch result -----
    # -- gate; that must look only at THIS BATCH's own runs, below). -----------
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

    # -- this batch's own runs only: every run_history row created since ------
    # -- RUN_COUNT_BEFORE (the count captured right before this batch started).
    # -- run_history is immutable + append-only, ordered by (started_at, ------
    # -- rowid) ascending, so "skip the first RUN_COUNT_BEFORE rows" is -------
    # -- exactly "this batch's rows", regardless of how many separate --------
    # -- run_history rows the run-lifecycle ended up creating.
    print()
    print("--- this batch's runs (machine-parsed by the calling shell script) ---")
    all_runs = db.query(
        "SELECT run_id, status AS run_status, fetched_count, inserted_count, updated_count, "
        "duplicate_count, review_count, error_count, discovered_count "
        "FROM run_history WHERE job_id=? ORDER BY started_at ASC, rowid ASC", (job_id,),
    )
    batch_runs = all_runs[run_count_before:] if run_count_before is not None else all_runs
    run_count = len(batch_runs)
    fetched_total = sum(r["fetched_count"] or 0 for r in batch_runs)
    inserted_total = sum(r["inserted_count"] or 0 for r in batch_runs)
    updated_total = sum(r["updated_count"] or 0 for r in batch_runs)
    duplicate_total = sum(r["duplicate_count"] or 0 for r in batch_runs)
    review_total = sum(r["review_count"] or 0 for r in batch_runs)
    error_total = sum(r["error_count"] or 0 for r in batch_runs)
    discovered_total_batch = sum(r["discovered_count"] or 0 for r in batch_runs)
    non_completed_runs = [r["run_id"] for r in batch_runs if r["run_status"] != "completed"]

    print(f"RUN_COUNT={run_count}")
    print(f"FETCHED_TOTAL_THIS_BATCH={fetched_total}")
    print(f"INSERTED_TOTAL_THIS_BATCH={inserted_total}")
    print(f"UPDATED_TOTAL_THIS_BATCH={updated_total}")
    print(f"DUPLICATE_TOTAL_THIS_BATCH={duplicate_total}")
    print(f"REVIEW_TOTAL_THIS_BATCH={review_total}")
    print(f"ERROR_TOTAL_THIS_BATCH={error_total}")
    print(f"DISCOVERED_TOTAL_THIS_BATCH={discovered_total_batch}")
    print(f"NON_COMPLETED_RUNS_THIS_BATCH={len(non_completed_runs)}")

    # LIFECYCLE_OK: every run this batch created actually finalized as
    # 'completed' (run_history is immutable -- a row that isn't 'completed'
    # here is either still running, which shouldn't be possible once the
    # watcher's poll loop has exited, or something failed), AND the job's
    # status snapshot right now is never the misleading 'retry' value for
    # what was actually a healthy, successful batch (error_total==0).
    lifecycle_ok = (not non_completed_runs) and not (job_status_snapshot == "retry" and error_total == 0)
    print(f"LIFECYCLE_OK={'YES' if lifecycle_ok else 'NO'}")

    # -- latest execution only -----------------------------------------------
    print()
    print("--- latest run (this execution only -- machine-parsed by the calling shell script) ---")
    latest_run = db.query_one(
        "SELECT run_id, status AS run_status, started_at, finished_at, discovered_count, "
        "fetched_count, inserted_count, updated_count, duplicate_count, review_count, error_count "
        "FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1",
        (job_id,),
    )
    print(f"RUN_ID={latest_run['run_id'] if latest_run else 'none'}")
    print(f"LATEST_RUN_ID={latest_run['run_id'] if latest_run else 'none'}")
    print(f"LATEST_RUN_STATUS={latest_run['run_status'] if latest_run else 'none'}")
    print(f"LATEST_RUN_STARTED_AT={latest_run['started_at'] if latest_run else 'none'}")
    print(f"LATEST_RUN_FINISHED_AT={latest_run['finished_at'] if latest_run else 'none'}")
    print(f"LATEST_RUN_ERROR_COUNT={latest_run['error_count'] if latest_run else -1}")
    print(f"OPEN_REVIEW_COUNT={n_open_review}")
    print(f"ENTITY_COUNT={n_entities}")
    print(f"DISCOVERED_COUNT={latest_run['discovered_count'] if latest_run else 0}")
    print(f"BATCH_DISCOVERED={latest_run['discovered_count'] if latest_run else 0}")
    print(f"FETCHED_COUNT={fetched_total}")
    print(f"BATCH_FETCHED={fetched_total}")
    print(f"INSERTED_COUNT={inserted_total}")
    print(f"BATCH_INSERTED={inserted_total}")
    print(f"UPDATED_COUNT={updated_total}")
    print(f"BATCH_UPDATED={updated_total}")
    print(f"BATCH_DUPLICATES={duplicate_total}")
    print(f"BATCH_REVIEWS={review_total}")
    print(f"ERROR_COUNT={error_total}")
    print(f"BATCH_ERRORS={error_total}")

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
