from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dashboard.ledger import connect, pr_snapshot
from dashboard.gh import pr_state, sweep_pr_status
from orchestrator.layout import Layout


class TestGh(unittest.TestCase):
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

    def test_pr_state_open(self):
        def fake_runner(args, cwd):
            return True, '{"number":42,"url":"http://pr/42","state":"OPEN"}'

        result = pr_state(Path("/tmp"), "plan/alpha", _runner=fake_runner)
        self.assertEqual(result, {"number": 42, "url": "http://pr/42", "state": "OPEN"})

    def test_pr_state_merged(self):
        def fake_runner(args, cwd):
            return True, '{"number":1,"url":"http://pr/1","state":"MERGED"}'

        result = pr_state(Path("/tmp"), "plan/beta", _runner=fake_runner)
        self.assertEqual(result, {"number": 1, "url": "http://pr/1", "state": "MERGED"})

    def test_pr_state_error_returns_none(self):
        def fake_runner(args, cwd):
            return False, ""

        result = pr_state(Path("/tmp"), "plan/gamma", _runner=fake_runner)
        self.assertIsNone(result)

    def test_sweep_pr_status_upserts(self):
        root = Path(tempfile.mkdtemp())
        layout = Layout.under(root)
        self._plan(layout.awaiting_merge, "a.md", "---\nid: alpha\n---\n")

        def fake_runner(args, cwd):
            return True, '{"number":7,"url":"http://pr/7","state":"OPEN"}'

        sweep_pr_status(
            self.conn, layout, lambda pid: f"plan/{pid}",
            checked_at="2026-01-01T00:00:00Z", _runner=fake_runner,
        )
        snap = pr_snapshot(self.conn)
        self.assertEqual(snap["alpha"]["number"], 7)
        self.assertEqual(snap["alpha"]["state"], "OPEN")

    def test_sweep_pr_status_skips_on_error(self):
        root = Path(tempfile.mkdtemp())
        layout = Layout.under(root)
        self._plan(layout.awaiting_merge, "a.md", "---\nid: alpha\n---\n")

        def fake_runner(args, cwd):
            return False, "error"

        sweep_pr_status(
            self.conn, layout, lambda pid: f"plan/{pid}",
            checked_at="2026-01-01T00:00:00Z", _runner=fake_runner,
        )
        self.assertEqual(pr_snapshot(self.conn), {})

    def test_sweep_pr_status_no_raise_on_invalid_plans(self):
        root = Path(tempfile.mkdtemp())
        layout = Layout.under(root)
        self._plan(layout.awaiting_merge, "bad.md", "no frontmatter\n")

        sweep_pr_status(
            self.conn, layout, lambda pid: f"plan/{pid}",
            checked_at="2026-01-01T00:00:00Z", _runner=lambda a, c: (False, ""),
        )
        self.assertEqual(pr_snapshot(self.conn), {})


if __name__ == "__main__":
    unittest.main()
