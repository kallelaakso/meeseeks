from __future__ import annotations

import subprocess
from pathlib import Path


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


def add_origin(root: Path) -> Path:
    """Give root a bare 'origin' remote with main pushed. Returns the remote."""
    remote = root.parent / f"{root.name}-origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)],
                   check=True, capture_output=True, text=True)
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True,
                                    capture_output=True, text=True)
    run("remote", "add", "origin", str(remote))
    run("push", "-q", "-u", "origin", "main")
    return remote
