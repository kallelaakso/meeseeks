"""SQLite event ledger for dashboard transitions and PR snapshots."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transitions (
  id          INTEGER PRIMARY KEY,
  plan_id     TEXT    NOT NULL,
  from_state  TEXT,
  to_state    TEXT    NOT NULL,
  observed_at TEXT    NOT NULL,
  is_baseline INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_transitions_plan
  ON transitions(plan_id, observed_at);

CREATE TABLE IF NOT EXISTS pr_status (
  plan_id    TEXT PRIMARY KEY,
  number     INTEGER,
  url        TEXT,
  state      TEXT,
  checked_at TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def record_transition(
    conn: sqlite3.Connection,
    plan_id: str,
    from_state: str | None,
    to_state: str,
    *,
    observed_at: str,
    is_baseline: bool = False,
) -> None:
    conn.execute(
        """
        INSERT INTO transitions (plan_id, from_state, to_state, observed_at, is_baseline)
        VALUES (?, ?, ?, ?, ?)
        """,
        (plan_id, from_state, to_state, observed_at, 1 if is_baseline else 0),
    )
    conn.commit()


def seed_baseline(
    conn: sqlite3.Connection,
    plan_id: str,
    state: str,
    *,
    observed_at: str,
) -> None:
    record_transition(
        conn, plan_id, from_state=None, to_state=state,
        observed_at=observed_at, is_baseline=True,
    )


def has_any_transitions(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM transitions LIMIT 1").fetchone()
    return row is not None


def latest_state(conn: sqlite3.Connection, plan_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT to_state FROM transitions
        WHERE plan_id = ?
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
        """,
        (plan_id,),
    ).fetchone()
    return row["to_state"] if row else None


def transitions_for(conn: sqlite3.Connection, plan_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, plan_id, from_state, to_state, observed_at, is_baseline
        FROM transitions
        WHERE plan_id = ?
        ORDER BY observed_at ASC, id ASC
        """,
        (plan_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def recent_transitions(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, plan_id, from_state, to_state, observed_at, is_baseline
        FROM transitions
        ORDER BY observed_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_pr(
    conn: sqlite3.Connection,
    plan_id: str,
    *,
    number: int | None,
    url: str | None,
    state: str | None,
    checked_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO pr_status (plan_id, number, url, state, checked_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(plan_id) DO UPDATE SET
          number = excluded.number,
          url = excluded.url,
          state = excluded.state,
          checked_at = excluded.checked_at
        """,
        (plan_id, number, url, state, checked_at),
    )
    conn.commit()


def pr_snapshot(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT plan_id, number, url, state, checked_at FROM pr_status"
    ).fetchall()
    return {
        r["plan_id"]: {
            "number": r["number"],
            "url": r["url"],
            "state": r["state"],
            "checked_at": r["checked_at"],
        }
        for r in rows
    }
