from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from orchestrator.layout import Layout


def make_layout(root: Path) -> Layout:
    """Create the full docs/plan dir tree under root and return a Layout."""
    layout = Layout.under(root)
    for d in (
        layout.ready,
        layout.in_progress,
        layout.awaiting_merge,
        layout.done,
        layout.closed,
        layout.failed,
        layout.worktrees,
        layout.logs,
    ):
        d.mkdir(parents=True, exist_ok=True)
    return layout


def init_repo(root: Path) -> None:
    """Init a git repo at root with one commit on branch main."""
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True,
                                    capture_output=True, text=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    (root / "README.md").write_text("init\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")
