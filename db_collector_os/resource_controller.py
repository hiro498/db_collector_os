"""Resource Controller: watches CPU/RAM/swap/disk/load and decides whether it
is safe to admit new jobs. Never kills a running job -- it only throttles new
admissions, so an already-running job is left to finish safely (or be
interrupted cleanly by the worker's own graceful-shutdown handling).
"""

from __future__ import annotations

from dataclasses import dataclass

import psutil

from .config import ResourceThresholds


@dataclass
class ResourceSnapshot:
    cpu_percent: float
    ram_percent: float
    swap_percent: float
    disk_percent: float
    load_average: float

    def as_dict(self) -> dict:
        return {
            "cpu_percent": self.cpu_percent,
            "ram_percent": self.ram_percent,
            "swap_percent": self.swap_percent,
            "disk_percent": self.disk_percent,
            "load_average": self.load_average,
        }


class ResourceController:
    def __init__(self, thresholds: ResourceThresholds, disk_path: str = "/"):
        self.thresholds = thresholds
        self.disk_path = disk_path

    def snapshot(self) -> ResourceSnapshot:
        cpu = psutil.cpu_percent(interval=0.1)
        vmem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage(self.disk_path)
        try:
            load1, _, _ = psutil.getloadavg()
        except (OSError, AttributeError):
            load1 = 0.0
        return ResourceSnapshot(
            cpu_percent=cpu,
            ram_percent=vmem.percent,
            swap_percent=swap.percent,
            disk_percent=disk.percent,
            load_average=load1,
        )

    def can_admit_new_job(self) -> tuple[bool, str]:
        snap = self.snapshot()
        t = self.thresholds
        if snap.cpu_percent > t.cpu_percent_max:
            return False, f"cpu {snap.cpu_percent:.1f}% > {t.cpu_percent_max}%"
        if snap.ram_percent > t.ram_percent_max:
            return False, f"ram {snap.ram_percent:.1f}% > {t.ram_percent_max}%"
        if snap.swap_percent > t.swap_percent_max:
            return False, f"swap {snap.swap_percent:.1f}% > {t.swap_percent_max}%"
        if snap.disk_percent > t.disk_percent_max:
            return False, f"disk {snap.disk_percent:.1f}% > {t.disk_percent_max}%"
        if snap.load_average > t.load_average_max:
            return False, f"load average {snap.load_average:.2f} > {t.load_average_max}"
        return True, "ok"
