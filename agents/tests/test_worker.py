from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import add_origin, init_repo, make_layout
from orchestrator.config import Config
from orchestrator.plans import parse_plan
from orchestrator.worker import run_plan


def _cfg(agent_command: str, verify: str = "true", mode: str = "auto-merge") -> Config:
    return Config(
        max_concurrency=1,
        poll_interval_seconds=1,
        integration_mode=mode,
        base_branch="main",
        verify_command=verify,
        agent_command=agent_command,
    )


class TestWorker(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        init_repo(self.root)
        self.layout = make_layout(self.root)
        self.plan_path = self.layout.ready / "p.md"
        self.plan_text = "---\nid: feat\n---\nbuild it\n"
        self.plan_path.write_text(self.plan_text)

    def test_success_moves_plan_to_done_and_lands_code(self):
        agent = "bash -c 'echo hi > OUT.txt && git add -A && git commit -q -m work'"
        result = run_plan(parse_plan(self.plan_path), self.layout, _cfg(agent))
        self.assertEqual(result, "done")
        self.assertTrue((self.layout.done / "p.md").exists())
        self.assertFalse((self.layout.ready / "p.md").exists())
        self.assertTrue((self.root / "OUT.txt").exists())

    def test_agent_failure_moves_plan_to_failed(self):
        agent = "bash -c 'exit 1'"
        result = run_plan(parse_plan(self.plan_path), self.layout, _cfg(agent))
        self.assertEqual(result, "failed")
        self.assertTrue((self.layout.failed / "p.md").exists())

    def test_lost_claim_returns_skipped(self):
        (self.layout.in_progress / "p.md").write_text(self.plan_path.read_text())
        self.plan_path.unlink()
        result = run_plan(parse_plan(self.layout.in_progress / "p.md"),
                          self.layout, _cfg("true"))
        self.assertEqual(result, "skipped")

    def test_pr_mode_success_moves_plan_to_awaiting_merge(self):
        add_origin(self.root)
        agent = "bash -c 'echo hi > OUT.txt && git add -A && git commit -q -m work'"
        with patch("orchestrator.worker.integrate", return_value=True):
            result = run_plan(parse_plan(self.plan_path), self.layout,
                              _cfg(agent, mode="pr"))
        self.assertEqual(result, "awaiting-merge")
        self.assertTrue((self.layout.awaiting_merge / "p.md").exists())
        self.assertFalse((self.layout.ready / "p.md").exists())
        self.assertTrue((self.layout.worktrees / "feat").exists())

    def _push_to_remote_main(self, remote: Path, name: str, content: str) -> None:
        """Commit a file to origin/main via a throwaway clone, leaving local
        main behind — simulates work landing on the remote elsewhere."""
        clone = self.root.parent / f"{self.root.name}-{name}-clone"
        run = lambda *a: subprocess.run(["git", "-C", str(clone), *a],
                                        check=True, capture_output=True, text=True)
        subprocess.run(["git", "clone", "-q", str(remote), str(clone)],
                       check=True, capture_output=True, text=True)
        run("config", "user.email", "x@y.com")
        run("config", "user.name", "X")
        (clone / name).write_text(content)
        run("add", "-A")
        run("commit", "-q", "-m", f"external {name}")
        run("push", "-q", "origin", "main")

    def test_pr_mode_worktree_branches_off_merged_remote_base(self):
        """Regression: a dependency merged on origin (local base stale) must be
        present in a dependent's worktree, so the agent doesn't redo it."""
        remote = add_origin(self.root)
        self._push_to_remote_main(remote, "dep.txt", "from dependency\n")
        # Agent only succeeds if the merged dep.txt is in its worktree.
        agent = "bash -c 'test -f dep.txt && echo ok > OUT.txt'"
        with patch("orchestrator.worker.integrate", return_value=True):
            result = run_plan(parse_plan(self.plan_path), self.layout,
                              _cfg(agent, mode="pr"))
        self.assertEqual(result, "awaiting-merge")
        self.assertTrue((self.layout.worktrees / "feat" / "dep.txt").exists())

    def test_auto_merge_syncs_local_base_with_remote_pushes(self):
        """Regression: in auto-merge mode, work pushed to the remote elsewhere
        (local base behind) must be fast-forwarded in before the worktree is
        branched off the local base."""
        remote = add_origin(self.root)
        self._push_to_remote_main(remote, "ext.txt", "pushed elsewhere\n")
        # Agent only succeeds if the externally-pushed ext.txt is present.
        agent = "bash -c 'test -f ext.txt && echo ok > OUT.txt'"
        result = run_plan(parse_plan(self.plan_path), self.layout,
                          _cfg(agent, mode="auto-merge"))
        self.assertEqual(result, "done")
        self.assertTrue((self.root / "OUT.txt").exists())

    def test_auto_merge_logs_when_local_base_diverged(self):
        """A non-ff divergence can't be fast-forwarded — log it and fall back
        to the local base rather than failing silently."""
        remote = add_origin(self.root)
        # Local main gains a commit not on the remote...
        run = lambda *a: subprocess.run(["git", "-C", str(self.root), *a],
                                        check=True, capture_output=True, text=True)
        (self.root / "local.txt").write_text("local only\n")
        run("add", "-A")
        run("commit", "-q", "-m", "local work")
        # ...while the remote gains a different commit -> diverged.
        self._push_to_remote_main(remote, "ext.txt", "remote only\n")
        result = run_plan(parse_plan(self.plan_path), self.layout,
                          _cfg("true", mode="auto-merge"))
        log = (self.layout.logs / "feat.log").read_text()
        self.assertIn("diverged", log)

    def test_agent_edits_no_commit_orchestrator_commits(self):
        agent = "bash -c 'echo hi > OUT.txt'"
        result = run_plan(parse_plan(self.plan_path), self.layout, _cfg(agent))
        self.assertEqual(result, "done")
        self.assertTrue((self.root / "OUT.txt").exists())
        # Exactly one commit on the merged branch (second parent of merge commit)
        count = subprocess.run(
            ["git", "-C", str(self.root), "rev-list", "--count", "main^2^..main^2"],
            capture_output=True, text=True,
        )
        self.assertEqual(count.stdout.strip(), "1")

    def test_agent_produces_no_changes_fails(self):
        agent = "true"
        result = run_plan(parse_plan(self.plan_path), self.layout, _cfg(agent))
        self.assertEqual(result, "failed")
        self.assertTrue((self.layout.failed / "p.md").exists())
        log = (self.layout.logs / "feat.log").read_text()
        self.assertIn("no commits — nothing to integrate", log)

    def test_plan_readable_in_worktree_never_committed(self):
        agent = "bash -c 'cp PLAN.md OUT.txt && git add -A && git commit -q -m w'"
        result = run_plan(parse_plan(self.plan_path), self.layout, _cfg(agent))
        self.assertEqual(result, "done")
        self.assertEqual((self.root / "OUT.txt").read_text(), self.plan_text)
        # PLAN.md must not be present in the committed tree on main
        ls = subprocess.run(
            ["git", "-C", str(self.root), "ls-tree", "-r", "HEAD", "--name-only"],
            capture_output=True, text=True,
        )
        self.assertNotIn("PLAN.md", ls.stdout)


if __name__ == "__main__":
    unittest.main()
