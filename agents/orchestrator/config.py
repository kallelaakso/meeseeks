from __future__ import annotations

import json
from dataclasses import MISSING, dataclass, fields
from pathlib import Path

COLUMN_KEYS = {"backlog", "spec_review", "ready", "in_progress",
               "in_review", "blocked", "done"}
LABEL_KEYS = {"arm", "failed", "blocked"}


@dataclass(frozen=True)
class Config:
    owner: str
    repo: str
    project_number: int
    bot_login: str
    reviewer: str
    base_branch: str
    spec_agent_command: str
    impl_agent_command: str
    verify_command: str
    columns: dict[str, str]
    labels: dict[str, str]
    remote: str = "origin"
    status_field: str = "Status"
    poll_interval_seconds: int = 30
    max_spec_concurrency: int = 1
    max_impl_concurrency: int = 3
    max_revision_attempts: int = 3

    @property
    def required_options(self) -> list[str]:
        """Column names that must exist on the board, in flow order."""
        return [self.columns[k] for k in
                ("backlog", "spec_review", "ready", "in_progress",
                 "in_review", "blocked", "done")]

    @property
    def blocking_labels(self) -> tuple[str, ...]:
        return (self.labels["failed"], self.labels["blocked"])

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"

    def agent_command(self, kind: str) -> str:
        return (self.spec_agent_command if kind == "spec"
                else self.impl_agent_command)

    def concurrency(self, kind: str) -> int:
        return (self.max_spec_concurrency if kind == "spec"
                else self.max_impl_concurrency)


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

    missing_columns = COLUMN_KEYS - data["columns"].keys()
    if missing_columns:
        raise ValueError(f"config columns missing: {sorted(missing_columns)}")
    missing_labels = LABEL_KEYS - data["labels"].keys()
    if missing_labels:
        raise ValueError(f"config labels missing: {sorted(missing_labels)}")

    if int(data.get("poll_interval_seconds", 30)) < 5:
        raise ValueError("poll_interval_seconds must be >= 5")
    for key in ("max_spec_concurrency", "max_impl_concurrency",
                "max_revision_attempts"):
        if int(data.get(key, 1)) < 1:
            raise ValueError(f"{key} must be >= 1")

    return Config(**data)
