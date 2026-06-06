from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dashboard.ledger import connect, record_transition, upsert_pr
from dashboard.server import Context, handle
from orchestrator.layout import Layout


class TestServer(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.layout = Layout.under(self.root)
        for d in (
            self.layout.ready,
            self.layout.in_progress,
            self.layout.awaiting_merge,
            self.layout.done,
            self.layout.closed,
            self.layout.failed,
            self.layout.repo / "docs" / "spec",
            self.layout.repo / "docs" / "plan" / "drafts",
        ):
            d.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(tempfile.mktemp(suffix=".db"))
        self.conn = connect(self.db_path)
        self.static_dir = self.root / "static"
        self.static_dir.mkdir(parents=True, exist_ok=True)
        self.ctx = Context(
            layout=self.layout, db_path=self.db_path, static_dir=self.static_dir
        )

    def tearDown(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def _plan(self, dir_: Path, name: str, body: str) -> Path:
        p = dir_ / name
        p.write_text(body)
        return p

    def _json(self, status, body):
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_api_board_shape(self):
        self._plan(
            self.layout.ready,
            "a.md",
            "---\nid: alpha\ndepends-on: []\nspec: foo.md\n---\n",
        )
        self._plan(
            self.layout.in_progress,
            "b.md",
            "---\nid: beta\ndepends-on: []\n---\n",
        )
        (self.layout.repo / "docs" / "spec" / "foo.md").write_text("# Foo\n")
        record_transition(
            self.conn,
            "alpha",
            "ready",
            "in-progress",
            observed_at="2026-01-01T00:00:00Z",
        )
        upsert_pr(
            self.conn,
            "alpha",
            number=1,
            url="http://pr/1",
            state="OPEN",
            checked_at="2026-01-01T00:00:00Z",
        )
        status, body, ct = handle("/api/board", {}, self.ctx)
        data = self._json(status, body)
        self.assertIn("plans", data)
        self.assertIn("specs", data)
        self.assertIn("invalid", data)
        self.assertIn("pr_checked_at", data)
        self.assertIn("generated_at", data)
        ready = data["plans"].get("ready-for-work", [])
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["id"], "alpha")
        self.assertEqual(ready[0]["spec"], "foo.md")
        self.assertIsNotNone(ready[0]["time_in_state_seconds"])
        self.assertEqual(ready[0]["pr"]["state"], "OPEN")
        self.assertEqual(data["pr_checked_at"], "2026-01-01T00:00:00Z")

    def test_api_plan_200(self):
        self._plan(
            self.layout.ready,
            "a.md",
            "---\nid: alpha\ndepends-on: []\n---\nbody",
        )
        status, body, ct = handle("/api/plan/alpha", {}, self.ctx)
        data = self._json(status, body)
        self.assertEqual(data["id"], "alpha")
        self.assertEqual(data["raw_markdown"], "---\nid: alpha\ndepends-on: []\n---\nbody")
        self.assertEqual(data["pr"], None)
        self.assertEqual(data["transitions"], [])

    def test_api_plan_404(self):
        status, body, ct = handle("/api/plan/nonexistent", {}, self.ctx)
        self.assertEqual(status, 404)
        data = json.loads(body)
        self.assertIn("error", data)

    def test_api_spec_rejects_path_traversal(self):
        status, body, ct = handle("/api/spec/../foo.md", {}, self.ctx)
        self.assertEqual(status, 400)
        data = json.loads(body)
        self.assertIn("error", data)

    def test_api_spec_200(self):
        (self.layout.repo / "docs" / "spec" / "foo.md").write_text("# Foo\n")
        self._plan(
            self.layout.ready,
            "a.md",
            "---\nid: alpha\ndepends-on: []\nspec: foo.md\n---\n",
        )
        status, body, ct = handle("/api/spec/foo.md", {}, self.ctx)
        data = self._json(status, body)
        self.assertEqual(data["filename"], "foo.md")
        self.assertEqual(data["status"], "planned")
        self.assertEqual(data["linked_plan_ids"], ["alpha"])
        self.assertEqual(data["raw_markdown"], "# Foo\n")

    def test_api_spec_404(self):
        status, body, ct = handle("/api/spec/missing.md", {}, self.ctx)
        self.assertEqual(status, 404)

    def test_api_events_limit(self):
        self._plan(
            self.layout.ready,
            "a.md",
            "---\nid: alpha\ndepends-on: []\n---\n",
        )
        record_transition(
            self.conn,
            "alpha",
            "ready",
            "in-progress",
            observed_at="2026-01-01T00:00:00Z",
        )
        record_transition(
            self.conn,
            "alpha",
            "in-progress",
            "done",
            observed_at="2026-01-02T00:00:00Z",
        )
        status, body, ct = handle("/api/events", {"limit": ["1"]}, self.ctx)
        data = self._json(status, body)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["to_state"], "done")

    def test_static_index(self):
        (self.static_dir / "index.html").write_text("<h1>hello</h1>")
        status, body, ct = handle("/", {}, self.ctx)
        self.assertEqual(status, 200)
        self.assertEqual(ct, "text/html")
        self.assertEqual(body, b"<h1>hello</h1>")

    def test_static_404(self):
        status, body, ct = handle("/static/missing.css", {}, self.ctx)
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
