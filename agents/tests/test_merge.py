from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import make_layout
from orchestrator.layout import Layout
from orchestrator.merge import sweep_pending_merges
from orchestrator.plans import list_plans


class TestMergeSweep(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.layout = make_layout(self.root)
        # Create two plans in awaiting-merge
        for slug in ("alpha", "beta"):
            p = self.layout.awaiting_merge / f"{slug}.md"
            p.write_text(f"---\nid: {slug}\n---\n")
        # Stub the worktree dir so remove_worktree can be called
        (self.layout.worktrees / "alpha").mkdir(parents=True, exist_ok=True)
        (self.layout.worktrees / "beta").mkdir(parents=True, exist_ok=True)

    def _ids(self, dir_: Path) -> set[str]:
        return {p.id for p in list_plans(dir_)}

    def test_merged_moves_to_done_and_removes_worktree(self):
        with patch("orchestrator.merge._pr_state", return_value="MERGED"), \
             patch("orchestrator.merge.remove_worktree") as mock_rm:
            sweep_pending_merges(self.layout)
        self.assertEqual(self._ids(self.layout.done), {"alpha", "beta"})
        self.assertEqual(self._ids(self.layout.awaiting_merge), set())
        self.assertEqual(mock_rm.call_count, 2)

    def test_closed_moves_to_closed(self):
        with patch("orchestrator.merge._pr_state", return_value="CLOSED"):
            sweep_pending_merges(self.layout)
        self.assertEqual(self._ids(self.layout.closed), {"alpha", "beta"})
        self.assertEqual(self._ids(self.layout.awaiting_merge), set())

    def test_open_stays_in_awaiting_merge(self):
        with patch("orchestrator.merge._pr_state", return_value="OPEN"):
            sweep_pending_merges(self.layout)
        self.assertEqual(self._ids(self.layout.awaiting_merge), {"alpha", "beta"})
        self.assertEqual(self._ids(self.layout.done), set())
        self.assertEqual(self._ids(self.layout.closed), set())

    def test_none_stays_in_awaiting_merge(self):
        with patch("orchestrator.merge._pr_state", return_value=None):
            sweep_pending_merges(self.layout)
        self.assertEqual(self._ids(self.layout.awaiting_merge), {"alpha", "beta"})
        self.assertEqual(self._ids(self.layout.done), set())
        self.assertEqual(self._ids(self.layout.closed), set())


if __name__ == "__main__":
    unittest.main()
