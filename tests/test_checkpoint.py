from __future__ import annotations

from db_collector_os.checkpoint import CheckpointStore


def test_load_missing_returns_empty_state(db, job_id):
    store = CheckpointStore(db)
    cp = store.load(job_id)
    assert cp["state"] == {}
    assert cp["run_id"] is None


def test_save_and_load_roundtrip(db, job_id):
    store = CheckpointStore(db)
    store.save(job_id, "run1", "collect", {"seeded": True, "page": 3})
    cp = store.load(job_id)
    assert cp["run_id"] == "run1"
    assert cp["phase"] == "collect"
    assert cp["state"] == {"seeded": True, "page": 3}


def test_update_state_merges(db, job_id):
    store = CheckpointStore(db)
    store.save(job_id, "run1", "discovery", {"a": 1})
    result = store.update_state(job_id, "run1", "discovery", b=2)
    assert result == {"a": 1, "b": 2}


def test_clear_removes_checkpoint(db, job_id):
    store = CheckpointStore(db)
    store.save(job_id, "run1", "collect", {"x": 1})
    store.clear(job_id)
    cp = store.load(job_id)
    assert cp["state"] == {}


def test_resume_survives_process_restart_simulation(db, job_id):
    """Simulates the VPS-reboot scenario: a fresh CheckpointStore instance
    against the same DB file must see the same state a killed process saved.
    """
    store1 = CheckpointStore(db)
    store1.save(job_id, "run1", "collect", {"fetch_queue_progress": 42})
    store2 = CheckpointStore(db)  # a "new process"
    cp = store2.load(job_id)
    assert cp["state"]["fetch_queue_progress"] == 42
