from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    )


def _git_quiet(repo: Path, *args: str) -> None:
    """Run a git command, ignoring failure (used for best-effort cleanup)."""
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def create_worktree(repo: Path, worktrees_dir: Path, slug: str,
                    base_branch: str) -> tuple[Path, str]:
    """Create a worktree on a fresh branch plan/<slug> based on base_branch.

    Idempotent: a previous (failed) run keeps its worktree + branch for
    debugging, which would otherwise make `git worktree add` collide. So we
    discard any leftover worktree/branch for this slug before recreating.
    """
    branch = f"plan/{slug}"
    wt = Path(worktrees_dir) / slug
    if wt.exists():
        _git_quiet(repo, "worktree", "remove", "--force", str(wt))
    _git_quiet(repo, "worktree", "prune")
    _git_quiet(repo, "branch", "-D", branch)
    _git(repo, "worktree", "add", "-b", branch, str(wt), base_branch)
    return wt, branch


def remove_worktree(repo: Path, worktree: Path) -> None:
    _git(repo, "worktree", "remove", "--force", str(worktree))
