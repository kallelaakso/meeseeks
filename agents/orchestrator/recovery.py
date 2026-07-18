from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from orchestrator.config import Config
from orchestrator.fsops import append_log, move_into
from orchestrator.layout import Layout
from orchestrator.plans import list_plans
from orchestrator.worktree import branch_name

GitRunner = Callable[[list[str]], subprocess.CompletedProcess]


def _default_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _branch_landed(repo: Path, remote: str, base_branch: str, branch: str,
                   git: GitRunner) -> bool:
    """True if the branch's work escaped the worker: pushed to remote or merged.

    Used to decide whether a stranded plan is safe to re-run. If the branch was
    already pushed (a PR may exist) or its commits are an ancestor of the base
    (merged), re-running would duplicate landed work — so the caller fails it for
    human triage instead.
    """
    pushed = git(["-C", str(repo), "ls-remote", "--heads", remote, branch])
    if pushed.returncode == 0 and pushed.stdout.strip():
        return True
    exists = git(["-C", str(repo), "rev-parse", "--verify", "--quiet", branch])
    if exists.returncode != 0:
        return False
    merged = git(["-C", str(repo), "merge-base", "--is-ancestor",
                  branch, base_branch])
    return merged.returncode == 0


def recover_stranded(layout: Layout, config: Config, *,
                     git: GitRunner = _default_git) -> list[str]:
    """Reclaim plans orphaned in in-progress/ at startup. Never raises.

    Any plan in in-progress/ when the daemon starts has no live worker (the
    daemon is the sole writer and tracks workers in memory). Unlanded plans go
    back to ready-for-work/; plans whose work already landed go to failed/ for
    triage. A per-plan probe error leaves that plan in place for the next start.
    Returns the ids moved back to ready-for-work/.
    """
    recovered: list[str] = []
    for plan in list_plans(layout.in_progress):
        log_path = layout.logs / f"{plan.id}.log"
        branch = branch_name(plan.id)
        try:
            if _branch_landed(layout.repo, config.remote, config.base_branch,
                              branch, git):
                append_log(log_path,
                           "interrupted after work landed; triage manually")
                move_into(plan.path, layout.failed)
            else:
                append_log(log_path, "recovered stranded in-progress plan")
                move_into(plan.path, layout.ready)
                recovered.append(plan.id)
        except Exception as exc:  # noqa: BLE001 — leave for next restart
            append_log(log_path,
                       f"recovery probe failed, leaving in-progress: {exc}")
    return recovered
