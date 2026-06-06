from __future__ import annotations

import json
from dataclasses import MISSING, dataclass, fields
from pathlib import Path

VALID_MODES = {"auto-merge", "pr"}


@dataclass(frozen=True)
class Config:
    max_concurrency: int
    poll_interval_seconds: int
    integration_mode: str
    base_branch: str
    verify_command: str
    agent_command: str
    merge_sweep_interval_seconds: int = 300
    remote: str = "origin"
    dashboard_port: int = 8787
    dashboard_poll_interval_seconds: float = 3.0
    dashboard_pr_sweep_interval_seconds: float = 60.0
    dashboard_db: str = "agents/dashboard.db"


def load_config(path: Path) -> Config:
    data = json.loads(Path(path).read_text())

    known = {f.name for f in fields(Config)}
    required = {f.name for f in fields(Config)
                if f.default is MISSING and f.default_factory is MISSING}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"config missing keys: {sorted(missing)}")
    extra = data.keys() - known
    if extra:
        raise ValueError(f"config has unknown keys: {sorted(extra)}")

    if data["integration_mode"] not in VALID_MODES:
        raise ValueError(
            f"integration_mode must be one of {sorted(VALID_MODES)}, "
            f"got {data['integration_mode']!r}"
        )
    if int(data["max_concurrency"]) < 1:
        raise ValueError("max_concurrency must be >= 1")
    if int(data["poll_interval_seconds"]) < 1:
        raise ValueError("poll_interval_seconds must be >= 1")
    if int(data.get("merge_sweep_interval_seconds", 300)) < 1:
        raise ValueError("merge_sweep_interval_seconds must be >= 1")
    if int(data.get("dashboard_port", 8787)) < 1:
        raise ValueError("dashboard_port must be >= 1")
    if float(data.get("dashboard_poll_interval_seconds", 3.0)) < 0.1:
        raise ValueError("dashboard_poll_interval_seconds must be >= 0.1")
    if float(data.get("dashboard_pr_sweep_interval_seconds", 60.0)) < 1:
        raise ValueError("dashboard_pr_sweep_interval_seconds must be >= 1")

    return Config(**data)
