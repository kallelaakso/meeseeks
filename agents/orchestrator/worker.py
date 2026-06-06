from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator.claim import claim
from orchestrator.config import Config
from orchestrator.fsops import append_log, move_into
from orchestrator.integrate import integrate
from orchestrator.layout import Layout
from orchestrator.plans import Plan
from orchestrator.worktree import create_worktree, remove_worktree


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
    try:
        wt, branch = create_worktree(layout.repo, layout.worktrees,
                                     plan.id, config.base_branch)
    except subprocess.CalledProcessError as exc:
        append_log(log_path, f"FAILED creating worktree: {exc}")
        move_into(claimed, layout.failed)
        return "failed"

    command = config.agent_command.format(
        plan_path=str(claimed.resolve()),
        branch=branch,
        worktree=str(wt),
        verify_command=config.verify_command,
    )

    agent_ok = _run_agent(command, wt, log_path)
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
