from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dashboard.ledger import connect, has_any_transitions, transitions_for
from dashboard.poller import apply_baseline, current_snapshot, detect_and_record, poll
from orchestrator.layout import Layout


class TestPoller(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(tempfile.mktemp(suffix=".db"))
        self.conn = connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def _plan(self, dir_: Path, name: str, body: str) -> Path:
        dir_.mkdir(parents=True, exist_ok=True)
        p = dir_ / name
        p.write_text(body)
        return p

    def test_current_snapshot(self):
        root = Path(tempfile.mkdtemp())
        layout = Layout.under(root)
        self._plan(layout.ready, "a.md", "---\nid: alpha\n---\n")
        self._plan(layout.in_progress, "b.md", "---\nid: beta\n---\n")
        snap = current_snapshot(layout)
        self.assertEqual(snap, {"alpha": "ready-for-work", "beta": "in-progress"})

    def test_apply_baseline_only_when_empty(self):
        snap = {"p1": "ready-for-work", "p2": "in-progress"}
        apply_baseline(self.conn, snap, observed_at="2026-01-01T00:00:00Z")
        self.assertTrue(has_any_transitions(self.conn))
        ts = transitions_for(self.conn, "p1")
        self.assertEqual(len(ts), 1)
        self.assertEqual(ts[0]["is_baseline"], 1)

        # Second call is a no-op because ledger is not empty
        apply_baseline(self.conn, snap, observed_at="2026-01-02T00:00:00Z")
        ts = transitions_for(self.conn, "p1")
        self.assertEqual(len(ts), 1)

    def test_detect_and_record_new_plan(self):
        prev = {}
        curr = {"p1": "ready-for-work"}
        transitions = detect_and_record(
            self.conn, prev, curr, observed_at="2026-01-01T00:00:00Z",
        )
        self.assertEqual(len(transitions), 1)
        self.assertIsNone(transitions[0]["from_state"])
        self.assertEqual(transitions[0]["to_state"], "ready-for-work")

    def test_detect_and_record_state_change(self):
        prev = {"p1": "ready-for-work"}
        curr = {"p1": "in-progress"}
        transitions = detect_and_record(
            self.conn, prev, curr, observed_at="2026-01-01T00:00:00Z",
        )
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["from_state"], "ready-for-work")
        self.assertEqual(transitions[0]["to_state"], "in-progress")

    def test_detect_and_record_no_change(self):
        prev = {"p1": "ready-for-work"}
        curr = {"p1": "ready-for-work"}
        transitions = detect_and_record(
            self.conn, prev, curr, observed_at="2026-01-01T00:00:00Z",
        )
        self.assertEqual(transitions, [])

    def test_poll_baseline_and_transition(self):
        root = Path(tempfile.mkdtemp())
        layout = Layout.under(root)
        self._plan(layout.ready, "a.md", "---\nid: alpha\n---\n")

        curr, transitions = poll(
            self.conn, layout, {}, observed_at="2026-01-01T00:00:00Z",
        )
        self.assertEqual(curr, {"alpha": "ready-for-work"})
        self.assertEqual(len(transitions), 1)
        self.assertIsNone(transitions[0]["from_state"])

        # Move plan to in-progress
        self._plan(layout.in_progress, "a.md", "---\nid: alpha\n---\n")
        (layout.ready / "a.md").unlink()

        curr, transitions = poll(
            self.conn, layout, curr, observed_at="2026-01-02T00:00:00Z",
        )
        self.assertEqual(curr, {"alpha": "in-progress"})
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["from_state"], "ready-for-work")
        self.assertEqual(transitions[0]["to_state"], "in-progress")

        # No change
        curr, transitions = poll(
            self.conn, layout, curr, observed_at="2026-01-03T00:00:00Z",
        )
        self.assertEqual(transitions, [])


if __name__ == "__main__":
    unittest.main()
