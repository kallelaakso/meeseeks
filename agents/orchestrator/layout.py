from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Layout:
    """The on-disk directory map. State = which dir a plan file lives in."""

    repo: Path
    ready: Path
    in_progress: Path
    done: Path
    failed: Path
    worktrees: Path
    logs: Path

    @classmethod
    def under(cls, repo: Path) -> "Layout":
        plan = repo / "docs" / "plan"
        return cls(
            repo=repo,
            ready=plan / "ready-for-work",
            in_progress=plan / "in-progress",
            done=plan / "done",
            failed=plan / "failed",
            worktrees=repo / ".worktrees",
            logs=repo / "agents" / "logs",
        )
