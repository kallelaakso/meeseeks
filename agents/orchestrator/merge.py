from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator.fsops import append_log, move_into
from orchestrator.layout import Layout
from orchestrator.plans import list_plans
from orchestrator.worktree import branch_name, remove_worktree


def _pr_state(repo: Path, branch: str) -> str | None:
    """PR state for branch: 'MERGED' | 'CLOSED' | 'OPEN', or None on error."""
    proc = subprocess.run(
        ["gh", "pr", "view", branch, "--json", "state", "-q", ".state"],
        cwd=str(repo), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def sweep_pending_merges(layout: Layout) -> None:
    """Advance awaiting-merge plans based on their PR state. Never raises."""
    for plan in list_plans(layout.awaiting_merge):
        log_path = layout.logs / f"{plan.id}.log"
        state = _pr_state(layout.repo, branch_name(plan.id))
        if state == "MERGED":
            append_log(log_path, "PR merged; moving to done")
            move_into(plan.path, layout.done)
            try:
                remove_worktree(layout.repo, layout.worktrees / plan.id)
            except subprocess.CalledProcessError:
                pass
        elif state == "CLOSED":
            append_log(log_path, "PR closed without merging; moving to closed")
            move_into(plan.path, layout.closed)
        elif state is None:
            append_log(log_path,
                       f"could not read PR state for {branch_name(plan.id)}; will retry")
        # OPEN: leave in place for the next sweep.
