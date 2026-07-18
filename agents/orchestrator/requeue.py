from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from orchestrator.fsops import append_log, move_into
from orchestrator.layout import Layout
from orchestrator.plans import list_plans


def requeue(plan_id: str, layout: Layout) -> Path:
    """Move a failed/ or closed/ plan back to ready-for-work/.

    Matches by parsed plan id (robust to filename drift). Never touches done/
    (audit trail + dependency gate). Appends a requeue marker to the plan's log
    so one log accumulates the full attempt history. Raises ValueError if the id
    is not present in failed/ or closed/.
    """
    for source_dir in (layout.failed, layout.closed):
        for plan in list_plans(source_dir):
            if plan.id == plan_id:
                dest = move_into(plan.path, layout.ready)
                stamp = datetime.now(timezone.utc).isoformat()
                append_log(layout.logs / f"{plan_id}.log", f"requeued at {stamp}")
                return dest
    raise ValueError(f"no failed/closed plan with id {plan_id!r}")
