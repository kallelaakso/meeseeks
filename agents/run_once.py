from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator.config import Config, load_config
from orchestrator.layout import Layout
from orchestrator.plans import eligible_plans
from orchestrator.recovery import recover_stranded
from orchestrator.worker import run_plan


def run_next(layout: Layout, config: Config) -> str | None:
    """Claim and run the first eligible plan. Returns its result or None."""
    for plan in eligible_plans(layout.ready, layout.done):
        return run_plan(plan, layout, config)
    return None


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    layout = Layout.under(repo)
    config = load_config(repo / "agents" / "config.json")
    recover_stranded(layout, config)
    result = run_next(layout, config)
    print(result or "no eligible plans")
    if result == "failed":
        print(f"see logs in {layout.logs}")
    return 0 if result in ("done", "awaiting-merge", None) else 1


if __name__ == "__main__":
    raise SystemExit(main())
