from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    )


def _git_quiet(repo: Path, *args: str) -> bool:
    """Run a git command, ignoring failure. Returns True on success."""
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.returncode == 0


def branch_name(slug: str) -> str:
    return f"plan/{slug}"


def fetch_base(repo: Path, remote: str, base_branch: str) -> None:
    """Fetch the remote base branch. Raises on failure.

    In pr mode a dependency's merge lands on the remote, not the local base, so a
    dependent's worktree must branch off the freshly-fetched <remote>/<base> to
    pick up that merged work — otherwise the agent redoes it and conflicts.
    """
    _git(repo, "fetch", remote, base_branch)


def _is_ancestor(repo: Path, maybe_ancestor: str, ref: str) -> bool:
    return _git_quiet(repo, "merge-base", "--is-ancestor", maybe_ancestor, ref)


def sync_base(repo: Path, remote: str, base_branch: str) -> str:
    """Best-effort fast-forward of local base_branch to <remote>/<base_branch>.

    In auto-merge mode merges land on the local base, but it can fall behind if
    work is pushed to the remote elsewhere. Pull that in before branching off it.
    Returns one of: 'synced' (local now contains the remote tip), 'unreachable'
    (remote/branch absent — auto-merge can run purely locally), or 'diverged'
    (non-ff: caller falls back to local base; worth logging).
    """
    if not _git_quiet(repo, "fetch", remote, base_branch):
        return "unreachable"
    remote_ref = f"{remote}/{base_branch}"
    if _is_ancestor(repo, remote_ref, base_branch):
        return "synced"  # local already contains the remote tip
    if _is_ancestor(repo, base_branch, remote_ref):
        # Remote strictly ahead: ff the ref, or the working tree if checked out.
        if not _git_quiet(repo, "fetch", remote, f"{base_branch}:{base_branch}"):
            _git_quiet(repo, "merge", "--ff-only", remote_ref)
        return "synced"
    return "diverged"


def create_worktree(repo: Path, worktrees_dir: Path, slug: str,
                    base_branch: str) -> tuple[Path, str]:
    """Create a worktree on a fresh branch plan/<slug> based on base_branch.

    Idempotent: a previous (failed) run keeps its worktree + branch for
    debugging, which would otherwise make `git worktree add` collide. So we
    discard any leftover worktree/branch for this slug before recreating.
    """
    branch = branch_name(slug)
    wt = Path(worktrees_dir) / slug
    if wt.exists():
        _git_quiet(repo, "worktree", "remove", "--force", str(wt))
    _git_quiet(repo, "worktree", "prune")
    _git_quiet(repo, "branch", "-D", branch)
    _git(repo, "worktree", "add", "-b", branch, str(wt), base_branch)
    return wt, branch


def create_worktree_on(repo: Path, worktrees_dir: Path, name: str,
                       branch: str, remote: str = "origin") -> Path:
    """Check out an existing remote branch into a fresh worktree.

    The claim already created the branch on the remote, so this fetches it
    rather than creating one. Idempotent: any leftover worktree or local branch
    of the same name is discarded first, so a retry after a crash is clean.
    """
    wt = Path(worktrees_dir) / name
    if wt.exists():
        _git_quiet(repo, "worktree", "remove", "--force", str(wt))
    _git_quiet(repo, "worktree", "prune")
    _git_quiet(repo, "branch", "-D", branch)
    _git(repo, "fetch", remote, branch)
    _git(repo, "worktree", "add", "-b", branch, str(wt), "FETCH_HEAD")
    return wt


def remove_worktree(repo: Path, worktree: Path) -> None:
    _git(repo, "worktree", "remove", "--force", str(worktree))
