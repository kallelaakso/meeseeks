from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import init_repo
from orchestrator.worktree import create_worktree
from orchestrator.integrate import integrate


def _commit_in(wt: Path, filename: str, content: str) -> None:
    (wt / filename).write_text(content)
    subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", "work"],
                   check=True, capture_output=True)


class TestIntegrate(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        init_repo(self.root)
        self.worktrees = self.root / ".worktrees"
        self.worktrees.mkdir()

    def test_auto_merge_success_lands_on_main(self):
        wt, branch = create_worktree(self.root, self.worktrees, "feat", "main")
        _commit_in(wt, "FEATURE.txt", "done\n")
        ok = integrate("auto-merge", self.root, wt, branch, "main", "true")
        self.assertTrue(ok)
        self.assertTrue((self.root / "FEATURE.txt").exists())

    def test_verify_failure_returns_false(self):
        wt, branch = create_worktree(self.root, self.worktrees, "feat", "main")
        _commit_in(wt, "FEATURE.txt", "done\n")
        ok = integrate("auto-merge", self.root, wt, branch, "main", "false")
        self.assertFalse(ok)
        self.assertFalse((self.root / "FEATURE.txt").exists())

    def test_pr_mode_short_circuits_on_verify_failure(self):
        wt, branch = create_worktree(self.root, self.worktrees, "feat", "main")
        _commit_in(wt, "FEATURE.txt", "done\n")
        ok = integrate("pr", self.root, wt, branch, "main", "false")
        self.assertFalse(ok)

    def test_auto_merge_targets_base_branch_not_current_checkout(self):
        # Primary repo sits on a different branch than base.
        subprocess.run(["git", "-C", str(self.root), "checkout", "-q", "-b", "other"],
                       check=True, capture_output=True)
        wt, branch = create_worktree(self.root, self.worktrees, "feat", "main")
        _commit_in(wt, "FEATURE.txt", "done\n")
        ok = integrate("auto-merge", self.root, wt, branch, "main", "true")
        self.assertTrue(ok)
        # The merge commit must be reachable from main, not from 'other'.
        on_main = subprocess.run(
            ["git", "-C", str(self.root), "log", "main", "--oneline"],
            capture_output=True, text=True, check=True).stdout
        self.assertIn("merge plan/feat", on_main)
        on_other = subprocess.run(
            ["git", "-C", str(self.root), "log", "other", "--oneline"],
            capture_output=True, text=True, check=True).stdout
        self.assertNotIn("FEATURE.txt", on_other)  # sanity: other untouched
        self.assertNotIn("merge plan/feat", on_other)


if __name__ == "__main__":
    unittest.main()
