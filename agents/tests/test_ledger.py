from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dashboard.ledger import (
    connect,
    has_any_transitions,
    latest_state,
    pr_snapshot,
    recent_transitions,
    record_transition,
    seed_baseline,
    transitions_for,
    upsert_pr,
)


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(tempfile.mktemp(suffix=".db"))
        self.conn = connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_connect_creates_schema(self):
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r["name"] for r in rows}
        self.assertIn("transitions", names)
        self.assertIn("pr_status", names)

    def test_connect_is_idempotent(self):
        conn2 = connect(self.db_path)
        rows = conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        self.assertIn("transitions", {r["name"] for r in rows})
        conn2.close()

    def test_has_any_transitions_empty(self):
        self.assertFalse(has_any_transitions(self.conn))

    def test_record_and_retrieve(self):
        record_transition(
            self.conn, "p1", "ready", "in-progress",
            observed_at="2026-01-01T00:00:00Z",
        )
        self.assertTrue(has_any_transitions(self.conn))

        ts = transitions_for(self.conn, "p1")
        self.assertEqual(len(ts), 1)
        self.assertEqual(ts[0]["plan_id"], "p1")
        self.assertEqual(ts[0]["from_state"], "ready")
        self.assertEqual(ts[0]["to_state"], "in-progress")
        self.assertEqual(ts[0]["is_baseline"], 0)

    def test_latest_state(self):
        record_transition(
            self.conn, "p1", "ready", "in-progress",
            observed_at="2026-01-01T00:00:00Z",
        )
        record_transition(
            self.conn, "p1", "in-progress", "done",
            observed_at="2026-01-02T00:00:00Z",
        )
        self.assertEqual(latest_state(self.conn, "p1"), "done")
        self.assertIsNone(latest_state(self.conn, "p2"))

    def test_seed_baseline(self):
        seed_baseline(self.conn, "p1", "ready", observed_at="2026-01-01T00:00:00Z")
        ts = transitions_for(self.conn, "p1")
        self.assertEqual(len(ts), 1)
        self.assertIsNone(ts[0]["from_state"])
        self.assertEqual(ts[0]["to_state"], "ready")
        self.assertEqual(ts[0]["is_baseline"], 1)

    def test_recent_transitions_order_and_limit(self):
        for i in range(3):
            record_transition(
                self.conn, f"p{i}", "ready", "in-progress",
                observed_at=f"2026-01-0{i+1}T00:00:00Z",
            )
        recent = recent_transitions(self.conn, limit=2)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["plan_id"], "p2")
        self.assertEqual(recent[1]["plan_id"], "p1")

    def test_upsert_pr_insert_and_update(self):
        upsert_pr(
            self.conn, "p1", number=42, url="http://pr/42",
            state="OPEN", checked_at="2026-01-01T00:00:00Z",
        )
        snap = pr_snapshot(self.conn)
        self.assertEqual(snap["p1"]["number"], 42)
        self.assertEqual(snap["p1"]["state"], "OPEN")

        upsert_pr(
            self.conn, "p1", number=43, url="http://pr/43",
            state="MERGED", checked_at="2026-01-02T00:00:00Z",
        )
        snap = pr_snapshot(self.conn)
        self.assertEqual(snap["p1"]["number"], 43)
        self.assertEqual(snap["p1"]["state"], "MERGED")


if __name__ == "__main__":
    unittest.main()
