from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Callable, Optional, Tuple, Union

from dashboard.ledger import upsert_pr
from orchestrator.layout import Layout
from orchestrator.plans import list_plans


Runner = Callable[[list[str], Optional[str]], Tuple[bool, str]]


def _default_runner(args: list[str], cwd: Optional[str]) -> Tuple[bool, str]:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout


def pr_state(
    repo: Path,
    branch: str,
    *,
    _runner: Optional[Runner] = None,
) -> Optional[dict]:
    runner = _runner or _default_runner
    ok, stdout = runner(
        ["gh", "pr", "view", branch, "--json", "number,url,state"],
        str(repo),
    )
    if not ok:
        return None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return {
        "number": data.get("number"),
        "url": data.get("url"),
        "state": data.get("state"),
    }


def sweep_pr_status(
    conn: sqlite3.Connection,
    layout: Layout,
    branch_of: Callable[[str], str],
    *,
    checked_at: str,
    _runner: Optional[Runner] = None,
) -> None:
    try:
        plans = list_plans(layout.awaiting_merge)
    except ValueError:
        return
    for plan in plans:
        info = pr_state(layout.repo, branch_of(plan.id), _runner=_runner)
        if info is not None:
            upsert_pr(
                conn, plan.id,
                number=info.get("number"),
                url=info.get("url"),
                state=info.get("state"),
                checked_at=checked_at,
            )
