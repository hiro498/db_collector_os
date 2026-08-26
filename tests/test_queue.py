from __future__ import annotations

from db_collector_os.fetching.queue import FetchQueue
from db_collector_os.models.enums import QueueStatus


def test_enqueue_dedupes_by_normalized_url(db, job_id):
    fq = FetchQueue(db)
    id1 = fq.enqueue(job_id, "https://example.com/a/?utm_source=x")
    id2 = fq.enqueue(job_id, "https://example.com/a/")
    assert id1 == id2


def test_claim_next_marks_fetching(db, job_id):
    fq = FetchQueue(db)
    fq.enqueue(job_id, "https://example.com/a")
    item = fq.claim_next(job_id)
    assert item is not None
    assert item["status"] == QueueStatus.FETCHING
    # nothing else queued -> next claim returns None
    assert fq.claim_next(job_id) is None


def test_claim_next_orders_by_priority(db, job_id):
    fq = FetchQueue(db)
    fq.enqueue(job_id, "https://example.com/low", priority=10)
    fq.enqueue(job_id, "https://example.com/high", priority=90)
    item = fq.claim_next(job_id)
    assert item["url"] == "https://example.com/high"


def test_mark_done(db, job_id):
    fq = FetchQueue(db)
    qid = fq.enqueue(job_id, "https://example.com/a")
    fq.claim_next(job_id)
    fq.mark_done(qid, 200, content_hash="abc123")
    stats = fq.stats(job_id)
    assert stats[QueueStatus.DONE] == 1


def test_mark_failed_retries_then_fails_permanently(db, job_id):
    fq = FetchQueue(db)
    qid = fq.enqueue(job_id, "https://example.com/a", max_attempts=2)
    fq.claim_next(job_id)
    fq.mark_failed(qid, "timeout")
    row = db.query_one("SELECT * FROM fetch_queue WHERE queue_id=?", (qid,))
    assert row["status"] == QueueStatus.QUEUED  # still has attempts left
    assert row["attempt_count"] == 1
    assert row["next_retry_at"] is not None

    fq.claim_next(job_id)
    fq.mark_failed(qid, "timeout again")
    row = db.query_one("SELECT * FROM fetch_queue WHERE queue_id=?", (qid,))
    assert row["status"] == QueueStatus.FAILED
    assert row["attempt_count"] == 2


def test_one_domain_failure_does_not_block_other_domains(db, job_id):
    fq = FetchQueue(db)
    fq.enqueue(job_id, "https://bad.example.com/a", max_attempts=1)
    fq.enqueue(job_id, "https://good.example.com/b")

    bad = fq.claim_next(job_id, ready_domains={"bad.example.com", "good.example.com"})
    fq.mark_failed(bad["queue_id"], "boom")  # permanently fails (max_attempts=1)

    good = fq.claim_next(job_id, ready_domains={"good.example.com"})
    assert good is not None
    assert good["domain"] == "good.example.com"


def test_requeue_stale_fetching(db, job_id):
    fq = FetchQueue(db)
    fq.enqueue(job_id, "https://example.com/a")
    fq.claim_next(job_id)  # leaves it 'fetching' as if the worker died
    n = fq.requeue_stale_fetching(job_id)
    assert n == 1
    assert fq.pending_count(job_id) == 1


def test_requeue_for_revalidation(db, job_id):
    fq = FetchQueue(db)
    qid = fq.enqueue(job_id, "https://example.com/a")
    fq.claim_next(job_id)
    fq.mark_done(qid, 200, content_hash="abc")
    n = fq.requeue_for_revalidation(job_id, older_than_seconds=0)
    assert n == 1
    assert fq.pending_count(job_id) == 1
