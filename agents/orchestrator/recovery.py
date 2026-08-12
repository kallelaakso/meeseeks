"""Reclaiming this machine's own orphans after a crash.

The daemon is the only process that spawns workers, so at startup every claim
in its ledger is orphaned by definition. The only question is whether the work
escaped — if it reached the remote, re-running would duplicate it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from orchestrator import claiming, ledger
from orchestrator.config import Config
from orchestrator.fsops import append_log
from orchestrator.github import GitHub

GitRunner = Callable[[list[str]], tuple[bool, str]]


def default_git(repo: Path) -> GitRunner:
    def run(args: list[str]) -> tuple[bool, str]:
        proc = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True)
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()

    return run


def work_escaped(git: GitRunner, cfg: Config, branch: str) -> bool:
    """True if the branch carries commits beyond base on the remote.

    Deliberately *not* `merge-base --is-ancestor branch base`: a claim branch
    with no commits sits exactly at base and is trivially an ancestor of it, so
    that test reports untouched work as landed and dead-ends the ticket.
    """
    ok, _ = git(["fetch", cfg.remote, branch])
    if not ok:
        return False
    ok, out = git(["rev-list", "--count",
                   f"{cfg.remote}/{cfg.base_branch}..FETCH_HEAD"])
    return ok and out.strip() not in ("", "0")


def goal_met(git: GitRunner, cfg: Config, kind: str, number: int) -> bool:
    """True if the claim's purpose is already achieved on the base branch.

    Asked *before* the escape check, because "some commits exist on the remote"
    is only a problem when the outcome is still pending. A leftover branch from
    a superseded pull request looks identical to abandoned work, and flagging a
    finished ticket for triage strands it in Blocked.
    """
    if kind != "spec":
        return False
    ok, out = git(["ls-tree", f"{cfg.remote}/{cfg.base_branch}",
                   "--name-only", "docs/spec/"])
    if not ok:
        return False
    return any(line.strip().split("/")[-1].startswith(f"{number}-")
               for line in out.splitlines())


def recover(gh: GitHub, cfg: Config, repo: Path, ledger_path: Path,
            logs_dir: Path, git: GitRunner | None = None) -> dict[int, str]:
    """Resolve every claim left in the ledger. Returns issue -> outcome."""
    git = git or default_git(repo)
    outcomes: dict[int, str] = {}
    for number, claim in ledger.load(ledger_path).items():
        log_path = logs_dir / f"{number}.log"
        try:
            if goal_met(git, cfg, claim.kind, number):
                claiming.release(gh, ledger_path, number, claim.branch)
                append_log(log_path, "claim already satisfied; released")
                outcomes[number] = "released"
            elif work_escaped(git, cfg, claim.branch):
                append_log(log_path,
                           "interrupted after work reached the remote")
                from orchestrator.janitor import fail
                fail(gh, cfg, number, "interrupted after work reached the "
                     "remote; needs triage", claim.branch, log_path)
                ledger.forget(ledger_path, number)
                outcomes[number] = "failed"
            else:
                claiming.release(gh, ledger_path, number, claim.branch)
                append_log(log_path, "released stranded claim")
                outcomes[number] = "released"
        except Exception as exc:  # noqa: BLE001 — retry on the next start
            append_log(log_path, f"recovery probe failed: {exc}")
            outcomes[number] = "deferred"
    return outcomes
