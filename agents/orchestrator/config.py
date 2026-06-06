from __future__ import annotations

import json
from dataclasses import dataclass, fields
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


def load_config(path: Path) -> Config:
    data = json.loads(Path(path).read_text())

    expected = {f.name for f in fields(Config)}
    missing = expected - data.keys()
    if missing:
        raise ValueError(f"config missing keys: {sorted(missing)}")
    extra = data.keys() - expected
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

    return Config(**data)
