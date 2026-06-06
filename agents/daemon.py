from __future__ import annotations

import sys
import time
from multiprocessing import Process
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator.config import Config, load_config
from orchestrator.layout import Layout
from orchestrator.merge import sweep_pending_merges
from orchestrator.plans import eligible_plans
from orchestrator.worker import OUTCOME, run_plan_as_process


def _spawn(plan, layout: Layout, config: Config) -> Process:
    p = Process(target=run_plan_as_process, args=(plan, layout, config),
                name=plan.id)
    p.start()
    print(f"daemon: started {plan.id}")
    return p


def poll_once(layout: Layout, config: Config, running: dict[str, Process]) -> None:
    # Reap finished workers and report their outcome.
    for plan_id in [pid for pid, proc in running.items() if not proc.is_alive()]:
        proc = running.pop(plan_id)
        proc.join()
        outcome = OUTCOME.get(proc.exitcode, f"crashed (exit {proc.exitcode})")
        line = f"daemon: {plan_id} -> {outcome}"
        if outcome not in ("done", "awaiting-merge"):
            line += f" (see {layout.logs / f'{plan_id}.log'})"
        print(line)
    # Fill free slots with eligible, not-already-running plans.
    for plan in eligible_plans(layout.ready, layout.done):
        if len(running) >= config.max_concurrency:
            break
        if plan.id in running:
            continue
        running[plan.id] = _spawn(plan, layout, config)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    layout = Layout.under(repo)
    config = load_config(repo / "agents" / "config.json")
    running: dict[str, Process] = {}
    last_sweep = 0.0  # 0 forces a sweep on the first iteration
    print(f"daemon: polling {layout.ready} every {config.poll_interval_seconds}s "
          f"(max_concurrency={config.max_concurrency}, mode={config.integration_mode}, "
          f"merge_sweep_interval={config.merge_sweep_interval_seconds}s)")
    try:
        while True:
            now = time.monotonic()
            if now - last_sweep >= config.merge_sweep_interval_seconds:
                sweep_pending_merges(layout)
                last_sweep = now
            poll_once(layout, config, running)
            time.sleep(config.poll_interval_seconds)
    except KeyboardInterrupt:
        print("daemon: shutting down, waiting for workers...")
        for proc in running.values():
            proc.join()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
