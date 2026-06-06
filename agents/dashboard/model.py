from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orchestrator.layout import Layout
from orchestrator.plans import parse_plan

_STATE_PRECEDENCE = {
    "done": 6,
    "awaiting-merge": 5,
    "in-progress": 4,
    "ready-for-work": 3,
    "drafts": 2,
    "closed": 1,
    "failed": 0,
}


def _plan_dirs(layout: Layout) -> list[tuple[Path, str]]:
    return [
        (layout.repo / "docs" / "plan" / "drafts", "drafts"),
        (layout.ready, "ready-for-work"),
        (layout.in_progress, "in-progress"),
        (layout.awaiting_merge, "awaiting-merge"),
        (layout.done, "done"),
        (layout.closed, "closed"),
        (layout.failed, "failed"),
    ]


@dataclass(frozen=True)
class PlanView:
    id: str
    state: str
    depends_on: list[str]
    spec: str | None
    path: Path
    filename: str


@dataclass(frozen=True)
class InvalidPlan:
    path: Path
    state: str
    error: str


@dataclass(frozen=True)
class SpecView:
    filename: str
    status: str
    linked_plan_ids: list[str]
    path: Path


def scan_plans(layout: Layout) -> tuple[dict[str, PlanView], list[InvalidPlan]]:
    views: dict[str, PlanView] = {}
    invalids: list[InvalidPlan] = []
    for dir_path, state in _plan_dirs(layout):
        if not dir_path.exists():
            continue
        for path in sorted(dir_path.glob("*.md")):
            try:
                parsed = parse_plan(path)
            except ValueError as exc:
                invalids.append(InvalidPlan(path=path, state=state, error=str(exc)))
                continue
            view = PlanView(
                id=parsed.id,
                state=state,
                depends_on=list(parsed.depends_on),
                spec=parsed.spec,
                path=parsed.path,
                filename=parsed.path.name,
            )
            if parsed.id in views:
                existing = views[parsed.id]
                if _STATE_PRECEDENCE.get(state, -1) > _STATE_PRECEDENCE.get(existing.state, -1):
                    views[parsed.id] = view
            else:
                views[parsed.id] = view
    return views, invalids


def rollup_spec_status(spec_file: str, plan_views: dict[str, PlanView]) -> str:
    linked = [v for v in plan_views.values() if v.spec == spec_file]
    if not linked:
        return "drafted"
    states = {v.state for v in linked}
    if "in-progress" in states:
        return "in-progress"
    if "ready-for-work" in states:
        return "planned"
    if "awaiting-merge" in states:
        return "in-review"
    if all(v.state == "done" for v in linked):
        return "done"
    if states <= {"failed", "closed"}:
        return "blocked"
    return "in-progress"


def scan_specs(layout: Layout, plan_views: dict[str, PlanView]) -> list[SpecView]:
    spec_dir = layout.repo / "docs" / "spec"
    if not spec_dir.exists():
        return []
    views: list[SpecView] = []
    for path in sorted(spec_dir.glob("*.md")):
        filename = path.name
        linked = [v.id for v in plan_views.values() if v.spec == filename]
        status = rollup_spec_status(filename, plan_views)
        views.append(
            SpecView(
                filename=filename,
                status=status,
                linked_plan_ids=linked,
                path=path,
            )
        )
    return views
