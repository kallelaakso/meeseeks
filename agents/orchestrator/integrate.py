from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable


def _run(cmd: list[str] | str, cwd: Path, shell: bool = False) -> tuple[bool, str]:
    """Run a command; return (ok, combined output). Never raises."""
    proc = subprocess.run(cmd, cwd=str(cwd), shell=shell,
                          capture_output=True, text=True)
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def integrate(mode: str, repo: Path, worktree: Path, branch: str,
              base_branch: str, verify_command: str,
              log_path: Path | None = None) -> bool:
    """Verify the worktree, then integrate per mode. Returns success bool."""
    def fail(msg: str) -> bool:
        if log_path is not None:
            with log_path.open("a") as log:
                log.write(f"[orchestrator] integration: {msg}\n")
        return False

    ok, out = _run(verify_command, cwd=worktree, shell=True)
    if not ok:
        return fail(f"verify '{verify_command}' failed: {out}")

    if mode == "auto-merge":
        return _auto_merge(repo, worktree, branch, base_branch, fail)
    if mode == "pr":
        return _open_pr(worktree, branch, fail)
    raise ValueError(f"unknown integration_mode: {mode!r}")


def _auto_merge(repo: Path, worktree: Path, branch: str, base_branch: str,
                fail: Callable[[str], bool]) -> bool:
    # Rebase the plan branch onto the latest base (run inside the worktree).
    ok, out = _run(["git", "rebase", base_branch], cwd=worktree)
    if not ok:
        _run(["git", "rebase", "--abort"], cwd=worktree)
        return fail(f"rebase onto {base_branch} failed: {out}")
    # Ensure the primary repo is on base_branch so the merge targets it
    # (git merge merges into the currently checked-out branch).
    ok, out = _run(["git", "-C", str(repo), "checkout", base_branch], cwd=repo)
    if not ok:
        return fail(f"checkout {base_branch} failed: {out}")
    # Merge the rebased branch into base from the primary repo.
    ok, out = _run(
        ["git", "-C", str(repo), "merge", "--no-ff", "-m",
         f"merge {branch}", branch],
        cwd=repo,
    )
    return True if ok else fail(f"merge {branch} failed: {out}")


def _open_pr(worktree: Path, branch: str, fail: Callable[[str], bool]) -> bool:
    ok, out = _run(["git", "push", "-u", "origin", branch], cwd=worktree)
    if not ok:
        return fail(f"git push failed: {out}")
    # Idempotent: if an OPEN PR already exists for this head, the push above
    # updated it — creating another would error. A closed/merged PR does not
    # count (gh pr view matches those too), so check open state explicitly.
    ok, out = _run(["gh", "pr", "list", "--head", branch, "--state", "open",
                    "--json", "number", "-q", ".[].number"], cwd=worktree)
    if ok and out.strip():
        return True
    ok, out = _run(["gh", "pr", "create", "--fill", "--head", branch], cwd=worktree)
    return True if ok else fail(f"gh pr create failed: {out}")
