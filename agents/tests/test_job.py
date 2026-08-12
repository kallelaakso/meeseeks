from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from orchestrator.config import Config
from orchestrator.github import GitHub
from orchestrator.job import EMPTY, FAILED, OPENED, pr_text, render_prompt, run_job
from tests.helpers import add_origin, init_repo


class TestRenderPrompt(unittest.TestCase):
    def test_replaces_tokens(self):
        out = render_prompt("issue {issue} on {branch}", issue="42",
                            branch="b")
        self.assertEqual(out, "issue 42 on b")

    def test_survives_braces_in_body(self):
        """Issue bodies contain code and JSON; str.format would blow up."""
        body = 'config is {"a": 1} and a set {x}'
        out = render_prompt("body:\n{body}", body=body)
        self.assertIn('{"a": 1}', out)
        self.assertIn("{x}", out)

    def test_unknown_placeholder_left_alone(self):
        self.assertEqual(render_prompt("{nope}", issue="1"), "{nope}")


class TestPrText(unittest.TestCase):
    def test_spec_pr_does_not_close_the_issue(self):
        title, body = pr_text("spec", 42, "Add OAuth")
        self.assertTrue(title.startswith("[spec]"))
        self.assertIn("Refs #42", body)
        self.assertNotIn("Closes", body)

    def test_impl_pr_closes_the_issue(self):
        title, body = pr_text("impl", 42, "Add OAuth")
        self.assertEqual(title, "Add OAuth")
        self.assertIn("Closes #42", body)


def _config(**overrides) -> Config:
    base = dict(
        owner="o", repo="r", project_number=1, bot_login="bot",
        reviewer="human", base_branch="main",
        spec_agent_command="true", impl_agent_command="true",
        verify_command="true",
        columns={k: k for k in ("backlog", "spec_review", "ready",
                                "in_progress", "in_review", "blocked", "done")},
        labels={"arm": "arm", "failed": "failed", "blocked": "blocked"},
    )
    base.update(overrides)
    return Config(**base)


class TestRunJob(unittest.TestCase):
    """Exercises the real git plumbing against a local bare remote."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "repo"
        self.root.mkdir()
        init_repo(self.root)
        add_origin(self.root)
        prompts = self.root / "agents" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "impl.md").write_text("do the thing for #{issue}")
        (prompts / "spec.md").write_text("spec the thing for #{issue}")
        self.log = self.root / "agents" / "logs" / "1.log"
        self.gh_calls: list[list[str]] = []
        # Claim: create the branch on the remote, as claiming.claim would.
        self.branch = "meeseeks/impl/1-slug"
        subprocess.run(["git", "-C", str(self.root), "push", "-q", "origin",
                        f"main:refs/heads/{self.branch}"], check=True)

    def _gh(self, open_pr: bool = False) -> GitHub:
        def runner(args, input=None):
            self.gh_calls.append(args)
            if "list" in args:
                return True, json.dumps([{"number": 9, "url": "u"}]
                                        if open_pr else [])
            return True, "https://pr"

        return GitHub("o", "r", run=runner)

    def _run(self, cfg: Config, gh: GitHub | None = None) -> str:
        return run_job("impl", 1, "slug", "Title", "Body", self.branch, cfg,
                       gh or self._gh(), self.root, self.log)

    def test_opens_pr_when_agent_produces_work(self):
        cfg = _config(impl_agent_command="echo hello > new.txt")
        self.assertEqual(self._run(cfg), OPENED)
        created = [c for c in self.gh_calls if "create" in c]
        self.assertEqual(len(created), 1)

    def test_empty_when_agent_changes_nothing(self):
        self.assertEqual(self._run(_config(impl_agent_command="true")), EMPTY)
        self.assertEqual([c for c in self.gh_calls if "create" in c], [])

    def test_failed_when_agent_exits_nonzero(self):
        cfg = _config(impl_agent_command="false")
        self.assertEqual(self._run(cfg), FAILED)

    def test_verify_failure_blocks_the_pr(self):
        cfg = _config(impl_agent_command="echo hello > new.txt",
                      verify_command="false")
        self.assertEqual(self._run(cfg), FAILED)
        self.assertEqual([c for c in self.gh_calls if "create" in c], [])

    def test_existing_pr_is_not_recreated(self):
        cfg = _config(impl_agent_command="echo hello > new.txt")
        self.assertEqual(self._run(cfg, self._gh(open_pr=True)), OPENED)
        self.assertEqual([c for c in self.gh_calls if "create" in c], [])

    def test_prompt_file_is_not_committed(self):
        cfg = _config(impl_agent_command="echo hello > new.txt")
        self._run(cfg)
        out = subprocess.run(
            ["git", "-C", str(self.root / ".worktrees" / "1-slug"),
             "ls-files"], capture_output=True, text=True).stdout
        self.assertNotIn(".meeseeks-prompt.md", out)


if __name__ == "__main__":
    unittest.main()
