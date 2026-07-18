from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import init_repo, make_layout
from orchestrator.config import Config
from orchestrator.recovery import recover_stranded


def _cfg() -> Config:
    return Config(
        max_concurrency=1,
        poll_interval_seconds=1,
        integration_mode="pr",
        base_branch="main",
        verify_command="true",
        agent_command="true",
    )


class TestRecovery(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        init_repo(self.root)
        self.layout = make_layout(self.root)

    def _stranded(self, plan_id: str) -> Path:
        p = self.layout.in_progress / f"{plan_id}.md"
        p.write_text(f"---\nid: {plan_id}\n---\nwork\n")
        return p

    def test_unlanded_plan_returns_to_ready(self):
        self._stranded("feat")
        git = lambda args: subprocess.CompletedProcess(args, 1, "", "")
        recovered = recover_stranded(self.layout, _cfg(), git=git)
        self.assertEqual(recovered, ["feat"])
        self.assertTrue((self.layout.ready / "feat.md").exists())
        self.assertFalse((self.layout.in_progress / "feat.md").exists())

    def test_pushed_plan_goes_to_failed(self):
        self._stranded("feat")

        def git(args):
            if "ls-remote" in args:
                return subprocess.CompletedProcess(
                    args, 0, "abc\trefs/heads/plan/feat\n", "")
            return subprocess.CompletedProcess(args, 1, "", "")

        recovered = recover_stranded(self.layout, _cfg(), git=git)
        self.assertEqual(recovered, [])
        self.assertTrue((self.layout.failed / "feat.md").exists())
        self.assertFalse((self.layout.in_progress / "feat.md").exists())

    def test_probe_error_leaves_plan_in_place(self):
        self._stranded("feat")

        def git(args):
            raise RuntimeError("boom")

        recovered = recover_stranded(self.layout, _cfg(), git=git)
        self.assertEqual(recovered, [])
        self.assertTrue((self.layout.in_progress / "feat.md").exists())

    def test_empty_in_progress_is_noop(self):
        git = lambda args: subprocess.CompletedProcess(args, 1, "", "")
        self.assertEqual(recover_stranded(self.layout, _cfg(), git=git), [])

    def test_run_once_recovers_before_running(self):
        import run_once
        self._stranded("feat")
        git = lambda args: subprocess.CompletedProcess(args, 1, "", "")
        # No eligible plans in ready yet; recovery should still move feat back.
        recovered = recover_stranded(self.layout, _cfg(), git=git)
        self.assertIn("feat", recovered)
        self.assertTrue((self.layout.ready / "feat.md").exists())


if __name__ == "__main__":
    unittest.main()
