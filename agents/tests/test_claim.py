from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.plans import parse_plan
from orchestrator.claim import claim


class TestClaim(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.ready = self.root / "ready"
        self.in_progress = self.root / "in-progress"
        self.ready.mkdir()
        self.in_progress.mkdir()
        self.plan_path = self.ready / "a.md"
        self.plan_path.write_text("---\nid: alpha\n---\nbody\n")
        self.plan = parse_plan(self.plan_path)

    def test_first_claim_moves_file_and_returns_path(self):
        dest = claim(self.plan, self.in_progress)
        self.assertIsNotNone(dest)
        self.assertTrue(dest.exists())
        self.assertFalse(self.plan_path.exists())
        self.assertEqual(dest.parent, self.in_progress)

    def test_second_claim_returns_none(self):
        first = claim(self.plan, self.in_progress)
        self.assertIsNotNone(first)
        second = claim(self.plan, self.in_progress)
        self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
