from __future__ import annotations

from db_collector_os.config import ResourceThresholds
from db_collector_os.resource_controller import ResourceController, ResourceSnapshot


def test_can_admit_when_under_thresholds(monkeypatch):
    controller = ResourceController(ResourceThresholds(cpu_percent_max=90, ram_percent_max=90))
    monkeypatch.setattr(
        controller, "snapshot",
        lambda: ResourceSnapshot(cpu_percent=10, ram_percent=20, swap_percent=0, disk_percent=30, load_average=0.5),
    )
    ok, reason = controller.can_admit_new_job()
    assert ok
    assert reason == "ok"


def test_blocks_new_admission_when_cpu_over_threshold(monkeypatch):
    controller = ResourceController(ResourceThresholds(cpu_percent_max=50))
    monkeypatch.setattr(
        controller, "snapshot",
        lambda: ResourceSnapshot(cpu_percent=95, ram_percent=20, swap_percent=0, disk_percent=30, load_average=0.5),
    )
    ok, reason = controller.can_admit_new_job()
    assert not ok
    assert "cpu" in reason


def test_blocks_new_admission_when_load_average_over_threshold(monkeypatch):
    controller = ResourceController(ResourceThresholds(load_average_max=1.0))
    monkeypatch.setattr(
        controller, "snapshot",
        lambda: ResourceSnapshot(cpu_percent=1, ram_percent=1, swap_percent=0, disk_percent=1, load_average=5.0),
    )
    ok, reason = controller.can_admit_new_job()
    assert not ok
    assert "load average" in reason


def test_snapshot_returns_real_values():
    controller = ResourceController(ResourceThresholds())
    snap = controller.snapshot()
    assert 0 <= snap.cpu_percent <= 100
    assert 0 <= snap.ram_percent <= 100
