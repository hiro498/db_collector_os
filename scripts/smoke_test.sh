#!/usr/bin/env bash
# DB Collector OS - production-safe smoke test.
#
# Verifies DB open/schema/integrity against the REAL production database
# (read-only operations only), then exercises job registry / fetch queue /
# worker / extraction / dedup end-to-end against a disposable temp database
# so it never touches production data and never makes a real network call.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

CLI="$APP_DIR/.venv/bin/db-collector"
PY="$APP_DIR/.venv/bin/python"
[ -x "$CLI" ] || CLI="db-collector"
[ -x "$PY" ] || PY="python3"

FAIL=0
step() { echo "--- $* ---"; }
ok() { echo "OK   $*"; }
bad() { echo "FAIL $*"; FAIL=1; }

step "production DB integrity"
if "$CLI" integrity >/tmp/dbc_smoke_integrity.$$ 2>&1; then
    ok "integrity_check ($(cat /tmp/dbc_smoke_integrity.$$))"
else
    bad "integrity_check: $(cat /tmp/dbc_smoke_integrity.$$)"
fi
rm -f /tmp/dbc_smoke_integrity.$$

step "production job registry readable"
if "$CLI" jobs list >/dev/null 2>&1; then
    ok "jobs list"
else
    bad "jobs list"
fi

step "production fetch queue readable"
if "$CLI" queue >/dev/null 2>&1; then
    ok "queue stats"
else
    bad "queue stats"
fi

step "offline pipeline exercise (disposable temp DB, no network)"
if "$PY" - <<'PYEOF'
import sys, tempfile, traceback
from pathlib import Path

def check(label, fn):
    try:
        fn()
        print(f"OK   {label}")
        return True
    except Exception:
        print(f"FAIL {label}")
        traceback.print_exc()
        return False

ok = True
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    from db_collector_os.database import Database
    from db_collector_os.job_registry import JobRegistry
    from db_collector_os.fetching.queue import FetchQueue
    from db_collector_os.entities import EntityStore
    from db_collector_os.deduplication import Deduplicator, compute_fingerprint
    from db_collector_os.adapters import get_adapter
    from db_collector_os.extraction.common import extract_common
    from db_collector_os.collectors import CollectorContext, get_collector
    from db_collector_os.config import AppConfig, ResourceThresholds
    from db_collector_os.models.enums import CollectorType

    db = Database(tmp / "smoke.sqlite3")

    def db_open_and_schema():
        tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"jobs", "entities", "fetch_queue", "entity_candidates", "review_queue"}
        assert required.issubset(tables), tables
    ok &= check("DB open + schema", db_open_and_schema)

    jr = JobRegistry(db)
    job_id = jr.create(
        job_name="Smoke Test Job", category="product", target_db="smoke", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="sample_official_site",
        config={"seed_urls": []},  # no seed URLs -> zero network calls
    )

    def job_registry_check():
        job = jr.get(job_id)
        assert job["status"] == "idle"
        due = jr.due_jobs()
        assert any(j["job_id"] == job_id for j in due)
    ok &= check("job registry create/get/due_jobs", job_registry_check)

    fq = FetchQueue(db)
    def queue_check():
        qid = fq.enqueue(job_id, "https://example.invalid/a")
        item = fq.claim_next(job_id)
        assert item is not None
        fq.mark_done(item["queue_id"], 200, content_hash="deadbeef")
        assert fq.stats(job_id).get("done") == 1
    ok &= check("fetch queue enqueue/claim/mark_done", queue_check)

    def worker_check():
        cfg = AppConfig(
            home_dir=tmp, db_path=tmp / "smoke.sqlite3", config_path=tmp / "config.yaml",
            resource_thresholds=ResourceThresholds(), log_dir=tmp / "logs",
        )
        cfg.log_dir.mkdir(parents=True, exist_ok=True)
        from db_collector_os.worker import Worker
        worker = Worker(cfg, worker_id="smoke-worker", db=db)
        jr.mark_queued(job_id)
        did_work = worker.run_one_job()
        assert did_work is True
    ok &= check("worker claims and runs a job (no network)", worker_check)

    def extraction_check():
        html = (
            '<html><head><title>Smoke Product</title>'
            '<script type="application/ld+json">{"@type":"Product","name":"Smoke Widget",'
            '"sku":"SMK-1","offers":{"price":"1.00","priceCurrency":"USD"}}</script>'
            '</head><body><h1>Smoke Widget</h1></body></html>'
        )
        common = extract_common(html, "https://example.invalid/p/1")
        adapter = get_adapter("sample_official_site")
        record = adapter.extract(common, "https://example.invalid/p/1", html)
        assert record.name == "Smoke Widget"
        assert not record.missing_required
        return record
    record_holder = {}
    def extraction_check_wrapped():
        record_holder["record"] = extraction_check()
    ok &= check("sample extraction (official_site adapter)", extraction_check_wrapped)

    def dedup_check():
        entities = EntityStore(db)
        dedup = Deduplicator(entities)
        fp = compute_fingerprint("product", normalized_name="smokewidget", domain="example.invalid")
        entities.create(
            job_id=job_id, entity_type="product", name="Smoke Widget", normalized_name="smokewidget",
            canonical_url=None, domain="example.invalid", address=None, telephone=None,
            external_id=None, fingerprint=fp, data={},
        )
        decision = dedup.resolve(
            job_id, "product", name="Smoke Widget", normalized_name="smokewidget", domain="example.invalid",
        )
        assert decision.action == "merge", decision.action
    ok &= check("duplicate detection", dedup_check)

    db.close()

sys.exit(0 if ok else 1)
PYEOF
then
    :
else
    bad "offline pipeline exercise"
fi

echo "==================================================="
if [ "$FAIL" -eq 0 ]; then
    echo "SMOKE TEST: PASS"
else
    echo "SMOKE TEST: FAIL"
fi
exit $FAIL
