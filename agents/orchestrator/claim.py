from __future__ import annotations

import os
from pathlib import Path

from orchestrator.plans import Plan


def claim(plan: Plan, in_progress_dir: Path) -> Path | None:
    """Atomically claim a plan by moving it into in_progress_dir.

    os.rename is atomic on a single filesystem: only one caller can move a
    given source path. A loser (source already gone) gets FileNotFoundError
    and receives None.
    """
    dest = Path(in_progress_dir) / plan.path.name
    try:
        os.rename(plan.path, dest)
    except FileNotFoundError:
        return None
    return dest
