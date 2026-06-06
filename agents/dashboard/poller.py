from __future__ import annotations

import sqlite3

from dashboard.ledger import has_any_transitions, record_transition, seed_baseline
from dashboard.model import scan_plans
from orchestrator.layout import Layout


def current_snapshot(layout: Layout) -> dict[str, str]:
    views, _invalids = scan_plans(layout)
    return {v.id: v.state for v in views.values()}


def apply_baseline(
    conn: sqlite3.Connection,
    snapshot: dict[str, str],
    *,
    observed_at: str,
) -> None:
    if has_any_transitions(conn):
        return
    for plan_id, state in snapshot.items():
        seed_baseline(conn, plan_id, state, observed_at=observed_at)


def detect_and_record(
    conn: sqlite3.Connection,
    prev: dict[str, str],
    curr: dict[str, str],
    *,
    observed_at: str,
) -> list[dict]:
    transitions: list[dict] = []
    for plan_id, state in curr.items():
        if plan_id not in prev:
            record_transition(
                conn, plan_id, from_state=None, to_state=state,
                observed_at=observed_at,
            )
            transitions.append({
                "plan_id": plan_id,
                "from_state": None,
                "to_state": state,
            })
        elif prev[plan_id] != state:
            record_transition(
                conn, plan_id, from_state=prev[plan_id], to_state=state,
                observed_at=observed_at,
            )
            transitions.append({
                "plan_id": plan_id,
                "from_state": prev[plan_id],
                "to_state": state,
            })
    # Plans that vanished (e.g. renamed) are ignored in v1.
    return transitions


def poll(
    conn: sqlite3.Connection,
    layout: Layout,
    prev_snapshot: dict[str, str],
    *,
    observed_at: str,
) -> tuple[dict[str, str], list[dict]]:
    curr = current_snapshot(layout)
    apply_baseline(conn, curr, observed_at=observed_at)
    transitions = detect_and_record(conn, prev_snapshot, curr, observed_at=observed_at)
    return curr, transitions
