from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_layout
from orchestrator.requeue import requeue


class TestRequeue(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.layout = make_layout(self.root)

    def _put(self, directory: Path, plan_id: str) -> Path:
        p = directory / f"{plan_id}.md"
        p.write_text(f"---\nid: {plan_id}\n---\nwork\n")
        return p

    def test_requeue_from_failed(self):
        self._put(self.layout.failed, "feat")
        dest = requeue("feat", self.layout)
        self.assertEqual(dest, self.layout.ready / "feat.md")
        self.assertTrue((self.layout.ready / "feat.md").exists())
        self.assertFalse((self.layout.failed / "feat.md").exists())
        self.assertIn("requeued at",
                      (self.layout.logs / "feat.log").read_text())

    def test_requeue_from_closed(self):
        self._put(self.layout.closed, "feat")
        requeue("feat", self.layout)
        self.assertTrue((self.layout.ready / "feat.md").exists())
        self.assertFalse((self.layout.closed / "feat.md").exists())

    def test_requeue_rejects_done_only(self):
        self._put(self.layout.done, "feat")
        with self.assertRaises(ValueError):
            requeue("feat", self.layout)
        self.assertTrue((self.layout.done / "feat.md").exists())

    def test_requeue_rejects_unknown_id(self):
        with self.assertRaises(ValueError):
            requeue("nope", self.layout)


class TestRequeueCli(unittest.TestCase):
    def test_cli_usage_when_no_arg(self):
        import requeue as cli
        self.assertEqual(cli.main(["requeue.py"]), 2)

    def test_cli_usage_when_too_many_args(self):
        import requeue as cli
        self.assertEqual(cli.main(["requeue.py", "a", "b"]), 2)


if __name__ == "__main__":
    unittest.main()
