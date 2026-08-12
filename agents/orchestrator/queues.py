"""What is eligible to be worked, derived purely from evidence.

No I/O: given a snapshot of the world, these say what the daemon should pick
up. That makes the scheduling rules — including dependency gating, the subtlest
part — testable without touching GitHub.
"""

from __future__ import annotations

from orchestrator.evidence import Evidence
from orchestrator.tickets import parse_depends_on


def _blocked(issue, labels: dict[str, str]) -> bool:
    return bool({labels["failed"], labels["blocked"]} & set(issue.labels))


def _has_open_pr(ev: Evidence, number: int, kind: str) -> bool:
    return any(p.kind == kind for p in ev.open_prs.get(number, []))


def _claimed(ev: Evidence, number: int, kind: str) -> bool:
    return kind in ev.claim_refs.get(number, set())


def spec_queue(ev: Evidence, labels: dict[str, str]) -> list[int]:
    """Armed issues with no spec work in flight."""
    out = []
    for number, issue in sorted(ev.issues.items()):
        if issue.closed or _blocked(issue, labels):
            continue
        if labels["arm"] not in issue.labels:
            continue
        if _claimed(ev, number, "spec") or _has_open_pr(ev, number, "spec"):
            continue
        # A landed spec is done, whatever the label still says. Without this a
        # stale arm label would send the agent back to rewrite merged work.
        if number in ev.specs_landed:
            continue
        out.append(number)
    return out


def unmet_dependencies(ev: Evidence, number: int) -> list[int]:
    """Dependencies whose implementation has not merged into the base branch.

    Merged is the bar, not "marked done": a dependent branches off base, so a
    prerequisite that has not landed there would be redone and conflict.
    """
    issue = ev.issues.get(number)
    if issue is None:
        return []
    return [d for d in parse_depends_on(issue.body) if d not in ev.impl_merged]


def impl_queue(ev: Evidence, labels: dict[str, str]) -> list[int]:
    """Issues whose spec has landed and whose dependencies have merged."""
    out = []
    for number in sorted(ev.specs_landed):
        issue = ev.issues.get(number)
        if issue is None or issue.closed or _blocked(issue, labels):
            continue
        if number in ev.impl_merged:
            continue
        if _claimed(ev, number, "impl") or _has_open_pr(ev, number, "impl"):
            continue
        if unmet_dependencies(ev, number):
            continue
        out.append(number)
    return out


def dependency_cycles(ev: Evidence) -> list[list[int]]:
    """Cycles in the `Depends on:` graph, so they can be labelled rather than
    stalling silently forever."""
    graph = {n: parse_depends_on(i.body) for n, i in ev.issues.items()}
    cycles: list[list[int]] = []
    seen: set[frozenset[int]] = set()

    def walk(node: int, path: list[int], visiting: set[int]) -> None:
        for dep in graph.get(node, []):
            if dep in visiting:
                cycle = path[path.index(dep):]
                key = frozenset(cycle)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
                continue
            if dep not in graph:
                continue
            walk(dep, path + [dep], visiting | {dep})

    for number in sorted(graph):
        walk(number, [number], {number})
    return cycles
