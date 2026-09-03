"""Configuration for the viability assessment tool: a YAML file (thresholds,
scoring weights) loaded independently of the DB. Nothing here is hardcoded in
the scoring/judgement modules -- see config/viability.yaml for the defaults
and every tunable value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_RELATIVE_PATH = "viability.yaml"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value is not None else default


@dataclass
class ViabilityConfig:
    phase1_gate: dict[str, Any] = field(default_factory=dict)
    competition_classification: dict[str, Any] = field(default_factory=dict)
    scoring: dict[str, Any] = field(default_factory=dict)
    final_judgement: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None


def default_config_path(app_config_path: str | Path | None = None) -> Path:
    """Resolve the viability config path: explicit env var override, else a
    `viability.yaml` next to the app's own config file (config/default.yaml),
    else `config/viability.yaml` relative to the current working directory.
    """
    override = _env("DB_COLLECTOR_VIABILITY_CONFIG")
    if override:
        return Path(override)
    if app_config_path is not None:
        return Path(app_config_path).parent / _DEFAULT_RELATIVE_PATH
    return Path("./config") / _DEFAULT_RELATIVE_PATH


def load_viability_config(path: str | Path | None = None) -> ViabilityConfig:
    config_path = Path(path) if path is not None else default_config_path()
    raw: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

    return ViabilityConfig(
        phase1_gate=raw.get("phase1_gate", {}) or {},
        competition_classification=raw.get("competition_classification", {}) or {},
        scoring=raw.get("scoring", {}) or {},
        final_judgement=raw.get("final_judgement", {}) or {},
        raw=raw,
        source_path=config_path,
    )
