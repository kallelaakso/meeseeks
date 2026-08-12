"""Cross-machine mutual exclusion.

Creating a git ref is the only compare-and-swap GitHub gives us: the API
refuses to create a ref that already exists. That makes branch creation the
claim, taken before any agent runs, so a loser spends nothing. The lock object
is the work branch itself, so there is nothing separate to leak.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

from orchestrator import ledger, tickets
from orchestrator.github import GitHub


def claim(gh: GitHub, ledger_path: Path, kind: str, number: int, slug: str,
          base_sha: str, now: str, host: str | None = None) -> str | None:
    """Take the claim for (kind, issue). Returns the branch, or None if lost.

    None means another machine created the ref first. That is a normal outcome,
    not an error.
    """
    branch = tickets.branch(kind, number, slug)
    if not gh.create_ref(f"refs/heads/{branch}", base_sha):
        return None
    ledger.record(ledger_path, number, kind, branch, os.getpid(), now)
    gh.comment(
        number,
        f"🤖 claimed by meeseeks@{host or socket.gethostname()} · {now}",
    )
    return branch


def release(gh: GitHub, ledger_path: Path, number: int,
            branch: str) -> None:
    """Drop a claim: delete the remote ref and forget it locally.

    Idempotent — a ref already gone is success, since the goal is only that the
    claim no longer blocks a re-claim.
    """
    try:
        gh.delete_ref(f"refs/heads/{branch}")
    except Exception:  # noqa: BLE001 — already deleted is the common case
        pass
    ledger.forget(ledger_path, number)
