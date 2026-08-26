"""Configuration loading: YAML defaults overlaid with environment variables (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a declared dependency
    load_dotenv = None


def _load_dotenv_if_present() -> None:
    if load_dotenv is None:
        return
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value is not None else default


@dataclass
class ResourceThresholds:
    cpu_percent_max: float = 85.0
    ram_percent_max: float = 85.0
    swap_percent_max: float = 50.0
    disk_percent_max: float = 90.0
    load_average_max: float = 4.0
    check_interval_seconds: float = 15.0


@dataclass
class AppConfig:
    home_dir: Path
    db_path: Path
    config_path: Path
    admin_host: str = "127.0.0.1"
    admin_port: int = 8787
    user_agent: str = "DBCollectorOS/0.1"
    search_provider: str = ""
    search_api_key: str = ""
    log_level: str = "INFO"
    log_dir: Path = field(default_factory=lambda: Path("./var/logs"))
    scheduler_interval_seconds: float = 15.0
    worker_poll_interval_seconds: float = 5.0
    worker_heartbeat_seconds: float = 10.0
    worker_stale_seconds: float = 300.0
    resource_thresholds: ResourceThresholds = field(default_factory=ResourceThresholds)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def jobs_dir(self) -> Path:
        return self.config_path.parent / "jobs"

    @property
    def backups_dir(self) -> Path:
        return self.home_dir / "backups"

    @property
    def checkpoints_dir(self) -> Path:
        return self.home_dir / "checkpoints"


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration: YAML file, overridden by environment variables."""
    _load_dotenv_if_present()

    config_path = Path(config_path or _env("DB_COLLECTOR_CONFIG", "./config/default.yaml"))
    raw: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

    home_dir = Path(_env("DB_COLLECTOR_HOME", raw.get("home_dir", "./var"))).resolve()
    db_path_raw = _env("DB_COLLECTOR_DB_PATH", raw.get("db_path", "db_collector.sqlite3"))
    db_path = Path(db_path_raw)
    if not db_path.is_absolute():
        db_path = home_dir / db_path

    resource_raw = raw.get("resource_thresholds", {}) or {}
    resource_thresholds = ResourceThresholds(
        cpu_percent_max=float(resource_raw.get("cpu_percent_max", 85.0)),
        ram_percent_max=float(resource_raw.get("ram_percent_max", 85.0)),
        swap_percent_max=float(resource_raw.get("swap_percent_max", 50.0)),
        disk_percent_max=float(resource_raw.get("disk_percent_max", 90.0)),
        load_average_max=float(resource_raw.get("load_average_max", 4.0)),
        check_interval_seconds=float(resource_raw.get("check_interval_seconds", 15.0)),
    )

    cfg = AppConfig(
        home_dir=home_dir,
        db_path=db_path,
        config_path=config_path,
        admin_host=_env("DB_COLLECTOR_ADMIN_HOST", raw.get("admin_host", "127.0.0.1")),
        admin_port=int(_env("DB_COLLECTOR_ADMIN_PORT", str(raw.get("admin_port", 8787)))),
        user_agent=_env("DB_COLLECTOR_USER_AGENT", raw.get("user_agent", "DBCollectorOS/0.1")),
        search_provider=_env("DB_COLLECTOR_SEARCH_PROVIDER", raw.get("search_provider", "")) or "",
        search_api_key=_env("DB_COLLECTOR_SEARCH_API_KEY", raw.get("search_api_key", "")) or "",
        log_level=_env("DB_COLLECTOR_LOG_LEVEL", raw.get("log_level", "INFO")),
        log_dir=home_dir / "logs",
        scheduler_interval_seconds=float(raw.get("scheduler_interval_seconds", 15.0)),
        worker_poll_interval_seconds=float(raw.get("worker_poll_interval_seconds", 5.0)),
        worker_heartbeat_seconds=float(raw.get("worker_heartbeat_seconds", 10.0)),
        worker_stale_seconds=float(raw.get("worker_stale_seconds", 300.0)),
        resource_thresholds=resource_thresholds,
        raw=raw,
    )

    for d in (cfg.home_dir, cfg.log_dir, cfg.backups_dir, cfg.checkpoints_dir, cfg.db_path.parent):
        d.mkdir(parents=True, exist_ok=True)

    return cfg
