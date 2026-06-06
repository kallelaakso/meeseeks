from __future__ import annotations

import json
import mimetypes
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dashboard.clock import now_iso
from dashboard.ledger import (
    connect,
    pr_snapshot,
    recent_transitions,
    transitions_for,
)
from dashboard.model import scan_plans, scan_specs
from orchestrator.layout import Layout


@dataclass
class Context:
    layout: Layout
    db_path: Path
    static_dir: Path


MAX_EVENTS = 2000

_STATE_ORDER = [
    "drafts",
    "ready-for-work",
    "in-progress",
    "awaiting-merge",
    "done",
    "failed",
    "closed",
]


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _time_in_state_seconds(conn: sqlite3.Connection, plan_id: str) -> float | None:
    row = conn.execute(
        """
        SELECT observed_at, is_baseline FROM transitions
        WHERE plan_id = ?
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
        """,
        (plan_id,),
    ).fetchone()
    if row is None or row["is_baseline"]:
        return None
    observed = _parse_iso(row["observed_at"])
    return (datetime.now(timezone.utc) - observed).total_seconds()


def _latest_pr_checked_at(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT MAX(checked_at) as checked_at FROM pr_status"
    ).fetchone()
    return row["checked_at"] if row and row["checked_at"] else None


def _api_board(ctx: Context) -> tuple[int, bytes, str]:
    conn = connect(ctx.db_path)
    try:
        plan_views, invalids = scan_plans(ctx.layout)
        specs = scan_specs(ctx.layout, plan_views)
        pr_snap = pr_snapshot(conn)
        pr_checked_at = _latest_pr_checked_at(conn)

        plans_by_state: dict[str, list[dict]] = {}
        for state in _STATE_ORDER:
            plans_by_state[state] = []

        for plan_id, view in plan_views.items():
            time_in_state = _time_in_state_seconds(conn, plan_id)
            plans_by_state[view.state].append(
                {
                    "id": view.id,
                    "state": view.state,
                    "depends_on": list(view.depends_on),
                    "spec": view.spec,
                    "filename": view.filename,
                    "time_in_state_seconds": time_in_state,
                    "pr": pr_snap.get(plan_id),
                }
            )

        spec_list = [
            {
                "filename": s.filename,
                "status": s.status,
                "linked_plan_ids": list(s.linked_plan_ids),
            }
            for s in specs
        ]

        invalid_list = [
            {
                "filename": i.path.name,
                "state": i.state,
                "error": i.error,
            }
            for i in invalids
        ]

        board = {
            "plans": plans_by_state,
            "specs": spec_list,
            "invalid": invalid_list,
            "pr_checked_at": pr_checked_at,
            "generated_at": now_iso(),
        }
        return 200, json.dumps(board).encode(), "application/json"
    finally:
        conn.close()


def _api_plan(plan_id: str, ctx: Context) -> tuple[int, bytes, str]:
    conn = connect(ctx.db_path)
    try:
        plan_views, _ = scan_plans(ctx.layout)
        view = plan_views.get(plan_id)
        if not view:
            return 404, json.dumps({"error": "plan not found"}).encode(), "application/json"
        raw = view.path.read_text()
        transitions = transitions_for(conn, plan_id)
        pr_snap = pr_snapshot(conn)
        body = {
            "id": view.id,
            "state": view.state,
            "depends_on": list(view.depends_on),
            "spec": view.spec,
            "raw_markdown": raw,
            "transitions": transitions,
            "pr": pr_snap.get(plan_id),
        }
        return 200, json.dumps(body).encode(), "application/json"
    finally:
        conn.close()


def _api_spec(filename: str, ctx: Context) -> tuple[int, bytes, str]:
    if "/" in filename or ".." in filename:
        return 400, json.dumps({"error": "invalid filename"}).encode(), "application/json"
    conn = connect(ctx.db_path)
    try:
        plan_views, _ = scan_plans(ctx.layout)
        spec_dir = ctx.layout.repo / "docs" / "spec"
        path = spec_dir / filename
        if not path.exists() or not path.is_file():
            return 404, json.dumps({"error": "spec not found"}).encode(), "application/json"
        raw = path.read_text()
        specs = scan_specs(ctx.layout, plan_views)
        spec = next((s for s in specs if s.filename == filename), None)
        if not spec:
            return 404, json.dumps({"error": "spec not found"}).encode(), "application/json"
        body = {
            "filename": spec.filename,
            "status": spec.status,
            "linked_plan_ids": list(spec.linked_plan_ids),
            "raw_markdown": raw,
        }
        return 200, json.dumps(body).encode(), "application/json"
    finally:
        conn.close()


def _api_events(query: dict[str, list[str]], ctx: Context) -> tuple[int, bytes, str]:
    limit = MAX_EVENTS
    if "limit" in query:
        raw = query["limit"][0]
        if raw == "all":
            limit = MAX_EVENTS
        else:
            try:
                limit = int(raw)
                if limit <= 0:
                    limit = MAX_EVENTS
                else:
                    limit = min(limit, MAX_EVENTS)
            except (ValueError, IndexError):
                limit = MAX_EVENTS
    conn = connect(ctx.db_path)
    try:
        events = recent_transitions(conn, limit=limit)
        return 200, json.dumps(events).encode(), "application/json"
    finally:
        conn.close()


def _serve_static(path: str, ctx: Context) -> tuple[int, bytes, str]:
    if path == "/":
        path = "/index.html"
    if path.startswith("/static/"):
        rel = Path(path[len("/static/"):])
    elif path == "/index.html":
        rel = Path("index.html")
    else:
        return 404, b"not found", "text/plain"

    if any(part == ".." for part in rel.parts):
        return 404, b"not found", "text/plain"

    file_path = ctx.static_dir / rel
    if not file_path.exists() or not file_path.is_file():
        return 404, b"not found", "text/plain"

    try:
        file_path.resolve().relative_to(ctx.static_dir.resolve())
    except ValueError:
        return 404, b"not found", "text/plain"

    content_type, _ = mimetypes.guess_type(str(file_path))
    if content_type is None:
        content_type = "application/octet-stream"
    return 200, file_path.read_bytes(), content_type


def handle(
    path: str, query: dict[str, list[str]], ctx: Context
) -> tuple[int, bytes, str]:
    if path == "/api/board":
        return _api_board(ctx)
    if path.startswith("/api/plan/"):
        plan_id = path[len("/api/plan/"):]
        return _api_plan(plan_id, ctx)
    if path.startswith("/api/spec/"):
        filename = path[len("/api/spec/"):]
        return _api_spec(filename, ctx)
    if path == "/api/events":
        return _api_events(query, ctx)
    return _serve_static(path, ctx)


def make_handler(ctx: Context):
    from http.server import BaseHTTPRequestHandler

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            status, body, content_type = handle(
                parsed.path, parse_qs(parsed.query), ctx
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    return _Handler
