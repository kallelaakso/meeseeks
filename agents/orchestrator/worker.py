from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator.claim import claim
from orchestrator.config import Config
from orchestrator.fsops import append_log, move_into
from orchestrator.integrate import integrate
from orchestrator.layout import Layout
from orchestrator.plans import Plan
from orchestrator.worktree import create_worktree, fetch_base, remove_worktree, sync_base


def _commit_worktree(wt: Path, plan_id: str, base_ref: str,
                     log_path: Path) -> bool:
    """Commit any agent changes in the worktree; require a commit over base.

    Handles all agent behaviors: leaves changes dirty (we commit them), commits
    itself (nothing left to stage), or does nothing / edited elsewhere (no
    commit over base -> fail fast with a clear message).
    """
    subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True,
                   capture_output=True, text=True)
    staged = subprocess.run(["git", "-C", str(wt), "diff", "--cached", "--quiet"])
    if staged.returncode != 0:  # something staged
        subprocess.run(["git", "-C", str(wt), "commit", "-m", f"implement {plan_id}"],
                       check=True, capture_output=True, text=True)
    ahead = subprocess.run(
        ["git", "-C", str(wt), "rev-list", "--count", f"{base_ref}..HEAD"],
        capture_output=True, text=True,
    )
    if ahead.stdout.strip() == "0":
        append_log(log_path, "agent produced no commits — nothing to integrate")
        return False
    return True


def _run_agent(command: str, cwd: Path, log_path: Path) -> bool:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    append_log(log_path, f"running agent in {cwd}: {command}")
    with log_path.open("a") as log:
        proc = subprocess.run(command, cwd=str(cwd), shell=True,
                              stdout=log, stderr=subprocess.STDOUT, text=True)
    append_log(log_path, f"agent exited with code {proc.returncode}")
    return proc.returncode == 0


# Worker exit codes -> outcome, so a parent process can report results.
EXIT_CODE = {"done": 0, "awaiting-merge": 4, "failed": 2, "skipped": 3}
OUTCOME = {code: name for name, code in EXIT_CODE.items()}


def run_plan_as_process(plan: Plan, layout: Layout, config: Config) -> None:
    """Process entrypoint: run a plan and exit with its outcome code."""
    raise SystemExit(EXIT_CODE.get(run_plan(plan, layout, config), 1))


def run_plan(plan: Plan, layout: Layout, config: Config) -> str:
    """Run one plan end-to-end. Returns 'done', 'failed', or 'skipped'."""
    # Always claim from the ready dir by filename — the passed-in plan may have
    # been parsed from anywhere, but the canonical source is ready-for-work.
    source = layout.ready / plan.path.name
    claimed = claim(Plan(plan.id, plan.depends_on, source), layout.in_progress)
    if claimed is None:
        return "skipped"

    log_path = layout.logs / f"{plan.id}.log"
    # In pr mode dependency merges land on the remote, not the local base, so
    # branch off the freshly-fetched <remote>/<base> to inherit merged work. In
    # auto-merge mode merges land on the local base; just pull in any work pushed
    # to the remote elsewhere before branching off it.
    base_ref = config.base_branch
    try:
        if config.integration_mode == "pr":
            fetch_base(layout.repo, config.remote, config.base_branch)
            base_ref = f"{config.remote}/{config.base_branch}"
        elif sync_base(layout.repo, config.remote, config.base_branch) == "diverged":
            append_log(log_path,
                       f"local {config.base_branch} diverged from "
                       f"{config.remote}/{config.base_branch}; "
                       "branching off local base (no fast-forward)")
        wt, branch = create_worktree(layout.repo, layout.worktrees,
                                     plan.id, base_ref)
    except subprocess.CalledProcessError as exc:
        append_log(log_path, f"FAILED preparing worktree: {exc}")
        move_into(claimed, layout.failed)
        return "failed"

    plan_copy = wt / "PLAN.md"
    plan_copy.write_text(claimed.read_text())

    command = config.agent_command.format(
        plan_path="PLAN.md",
        branch=branch,
        worktree=str(wt),
        verify_command=config.verify_command,
    )

    agent_ok = _run_agent(command, wt, log_path)
    if agent_ok:
        plan_copy.unlink(missing_ok=True)
        agent_ok = _commit_worktree(wt, plan.id, base_ref, log_path)
    integrated = agent_ok and integrate(
        config.integration_mode, layout.repo, wt, branch,
        config.base_branch, config.verify_command, log_path,
    )

    if integrated:
        if config.integration_mode == "pr":
            append_log(log_path, "PR opened; awaiting human merge")
            move_into(claimed, layout.awaiting_merge)
            return "awaiting-merge"
        append_log(log_path, "DONE: agent succeeded and changes integrated")
        move_into(claimed, layout.done)
        try:
            remove_worktree(layout.repo, wt)
        except subprocess.CalledProcessError:
            pass
        return "done"

    # Failure: keep worktree + branch + log for debugging.
    reason = "integration failed" if agent_ok else "agent failed"
    append_log(log_path, f"FAILED: {reason} (worktree {wt} kept on branch {branch})")
    move_into(claimed, layout.failed)
    return "failed"
