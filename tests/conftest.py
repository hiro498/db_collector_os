from __future__ import annotations

from pathlib import Path

import pytest

from db_collector_os.config import AppConfig, ResourceThresholds
from db_collector_os.database import Database


@pytest.fixture
def tmp_home(tmp_path: Path) -> Path:
    home = tmp_path / "var"
    home.mkdir()
    return home


@pytest.fixture
def db(tmp_home: Path) -> Database:
    database = Database(tmp_home / "test.sqlite3")
    yield database
    database.close()


@pytest.fixture
def app_config(tmp_home: Path) -> AppConfig:
    cfg = AppConfig(
        home_dir=tmp_home,
        db_path=tmp_home / "test.sqlite3",
        config_path=tmp_home / "config.yaml",
        admin_host="127.0.0.1",
        admin_port=8787,
        user_agent="DBCollectorOS-Test/0.1",
        resource_thresholds=ResourceThresholds(),
        log_dir=tmp_home / "logs",
    )
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    cfg.backups_dir.mkdir(parents=True, exist_ok=True)
    cfg.checkpoints_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def insert_job(db: Database, job_id: str = "job1", **overrides) -> str:
    """Insert a minimal job row so FK-constrained child tables (fetch_queue,
    entities, checkpoints, ...) can be exercised directly in unit tests
    without going through the full JobRegistry API.
    """
    from db_collector_os.job_registry import JobRegistry

    defaults = dict(
        job_name="Unit Test Job", category="product", target_db="products", target_table="entities",
        collector_type="official_site", adapter="sample_official_site",
    )
    defaults.update(overrides)
    return JobRegistry(db).create(job_id=job_id, **defaults)


@pytest.fixture
def job_id(db: Database) -> str:
    return insert_job(db)
