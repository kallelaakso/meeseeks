"""Release a claim held by a machine that is never coming back.

The only escape hatch for cross-machine claims: a daemon releases its own
orphans automatically, but will not judge another machine's, because "stale"
and "slow" look identical from the outside.

    python3 agents/release.py 42
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator import claiming, ledger, tickets
from orchestrator.config import load_config
from orchestrator.github import GitHub
from orchestrator.paths import ConfigNotFound, Paths, find_root


def remote_claim_branches(root: Path, remote: str, number: int) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-remote", "--heads", remote, "meeseeks/*"],
        capture_output=True, text=True,
    )
    branches = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        branch = parts[1].removeprefix("refs/heads/")
        parsed = tickets.parse_branch(branch)
        if parsed and parsed[1] == number:
            branches.append(branch)
    return branches


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].isdigit():
        print(__doc__)
        return 2
    number = int(argv[1])
    try:
        paths = Paths(find_root())
    except ConfigNotFound as exc:
        print(f"release: {exc}")
        return 2
    cfg = load_config(paths.config)
    gh = GitHub(cfg.owner, cfg.repo)

    branches = remote_claim_branches(paths.root, cfg.remote, number)
    local = ledger.load(paths.ledger).get(number)
    if local and local.branch not in branches:
        branches.append(local.branch)

    if not branches:
        print(f"no claim found for #{number}")
        return 1

    for branch in branches:
        claiming.release(gh, paths.ledger, number, branch)
        print(f"released {branch}")
    gh.comment(number, f"🔓 claim released manually for #{number}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
