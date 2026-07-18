from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator.layout import Layout
from orchestrator.requeue import requeue


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 agents/requeue.py <plan-id>")
        return 2
    repo = Path(__file__).resolve().parents[1]
    layout = Layout.under(repo)
    try:
        dest = requeue(argv[1], layout)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    print(f"requeued -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
