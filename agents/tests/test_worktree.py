from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import init_repo
from orchestrator.worktree import create_worktree, remove_worktree


class TestWorktree(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        init_repo(self.root)
        self.worktrees = self.root / ".worktrees"
        self.worktrees.mkdir()

    def test_create_makes_branch_and_dir(self):
        wt, branch = create_worktree(self.root, self.worktrees, "my-slug", "main")
        self.assertEqual(branch, "plan/my-slug")
        self.assertTrue(wt.exists())
        self.assertTrue((wt / "README.md").exists())
        branches = subprocess.run(
            ["git", "-C", str(self.root), "branch", "--list", "plan/my-slug"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("plan/my-slug", branches)

    def test_create_is_idempotent_when_worktree_already_exists(self):
        # A prior failed run leaves its worktree + branch behind; recreating
        # for the same slug must succeed rather than collide.
        create_worktree(self.root, self.worktrees, "my-slug", "main")
        wt, branch = create_worktree(self.root, self.worktrees, "my-slug", "main")
        self.assertEqual(branch, "plan/my-slug")
        self.assertTrue((wt / "README.md").exists())

    def test_remove_deletes_worktree(self):
        wt, _ = create_worktree(self.root, self.worktrees, "my-slug", "main")
        remove_worktree(self.root, wt)
        self.assertFalse(wt.exists())


if __name__ == "__main__":
    unittest.main()
