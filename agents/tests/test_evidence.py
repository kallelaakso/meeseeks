from __future__ import annotations

import json
import unittest

from orchestrator.evidence import (
    Evidence,
    IssueEv,
    PullEv,
    _parse_claim_refs,
    _parse_specs_landed,
    gather,
)


class TestParseClaimRefs(unittest.TestCase):
    def test_parses_meeseeks_branches(self):
        stdout = (
            "abc123\trefs/heads/meeseeks/spec/1-foo\n"
            "def456\trefs/heads/meeseeks/impl/1-foo\n"
        )
        result = _parse_claim_refs(stdout)
        self.assertEqual(result, {1: {"spec", "impl"}})

    def test_ignores_foreign_branches(self):
        stdout = "abc123\trefs/heads/feature/x\n"
        self.assertEqual(_parse_claim_refs(stdout), {})

    def test_empty(self):
        self.assertEqual(_parse_claim_refs(""), {})


class TestParseSpecsLanded(unittest.TestCase):
    def test_parses_numbers(self):
        stdout = "100644 blob abc\tdocs/spec/1-foo.md\n"
        self.assertEqual(_parse_specs_landed(stdout), {1})

    def test_ignores_date_prefixed_legacy_specs(self):
        out = "docs/spec/2026-06-06-merge-aware-design.md\n"
        self.assertEqual(_parse_specs_landed(out), set())

    def test_ignores_non_matching(self):
        stdout = "abc\tdocs/spec/README.md\n"
        self.assertEqual(_parse_specs_landed(stdout), set())


class TestPullEv(unittest.TestCase):
    def test_has_unaddressed_changes_true(self):
        p = PullEv(
            number=1, kind="impl", issue=1, branch="b",
            head_sha="s", mergeable=None,
            head_committed_at="2024-01-01T00:00:00Z",
            last_change_request_at="2024-01-02T00:00:00Z",
        )
        self.assertTrue(p.has_unaddressed_changes)

    def test_has_unaddressed_changes_false(self):
        p = PullEv(
            number=1, kind="impl", issue=1, branch="b",
            head_sha="s", mergeable=None,
            head_committed_at="2024-01-02T00:00:00Z",
            last_change_request_at="2024-01-01T00:00:00Z",
        )
        self.assertFalse(p.has_unaddressed_changes)

    def test_has_unaddressed_changes_none_safe(self):
        p = PullEv(
            number=1, kind="impl", issue=1, branch="b",
            head_sha="s", mergeable=None,
            head_committed_at=None,
            last_change_request_at=None,
        )
        self.assertFalse(p.has_unaddressed_changes)

    def test_has_unaddressed_changes_no_commit_date(self):
        p = PullEv(
            number=1, kind="impl", issue=1, branch="b",
            head_sha="s", mergeable=None,
            head_committed_at=None,
            last_change_request_at="2024-01-01T00:00:00Z",
        )
        self.assertTrue(p.has_unaddressed_changes)


class TestGather(unittest.TestCase):
    def test_gather_structure(self):
        gh_calls: list = []
        git_calls: list = []

        def fake_gh_runner(args: list[str], input: str | None = None) -> tuple[bool, str]:
            gh_calls.append((args, input))
            if "issue" in args and "list" in args:
                return True, '[{"number":1,"title":"T","body":"B","labels":[{"name":"bug"}],"state":"OPEN"}]'
            if "pr" in args and "list" in args and "open" in args:
                return True, '[{"number":10,"headRefName":"meeseeks/impl/1-slug","headRefOid":"abc","title":"PR","mergeable":"MERGEABLE","url":"http://pr/10"}]'
            if "pr" in args and "list" in args and "merged" in args:
                return True, '[]'
            if "pr" in args and "view" in args and "commits" in args:
                return True, '"2024-01-01T00:00:00Z"'
            if "pr" in args and "view" in args and "reviews" in args:
                return True, '{"reviews":[]}'
            return True, "[]"

        def fake_git_runner(args: list[str]) -> tuple[bool, str]:
            git_calls.append(args)
            if "ls-remote" in args:
                return True, "abc\trefs/heads/meeseeks/spec/1-slug\n"
            if "ls-tree" in args:
                return True, "100644 blob abc\tdocs/spec/1-slug.md\n"
            return True, ""

        from orchestrator.github import GitHub
        gh = GitHub("o", "r", run=fake_gh_runner)
        ev = gather(gh, fake_git_runner, "main", ["bug"])

        self.assertIn(1, ev.issues)
        self.assertEqual(ev.issues[1].title, "T")
        self.assertEqual(ev.claim_refs[1], {"spec"})
        self.assertIn(1, ev.specs_landed)
        self.assertIn(1, ev.open_prs)
        self.assertEqual(ev.open_prs[1][0].kind, "impl")


class TestGatherCompleteness(unittest.TestCase):
    """Evidence must cover issues the label queue never sees."""

    def _gather(self, reviews_json: str):
        def fake_gh_runner(args, input=None):
            if "issue" in args and "list" in args:
                return True, json.dumps([
                    {"number": 1, "title": "open", "body": "", "labels": [],
                     "state": "OPEN"},
                    {"number": 2, "title": "closed", "body": "", "labels": [],
                     "state": "CLOSED"},
                ])
            if "pr" in args and "list" in args and "open" in args:
                return True, json.dumps([{
                    "number": 10, "headRefName": "meeseeks/impl/1-slug",
                    "headRefOid": "abc", "mergeable": "MERGEABLE",
                }])
            if "pr" in args and "view" in args and "commits" in args:
                return True, '"2024-01-01T00:00:00Z"'
            if "pr" in args and "view" in args and "reviews" in args:
                return True, reviews_json
            return True, "[]"

        def fake_git_runner(args):
            return True, ""

        from orchestrator.github import GitHub
        return gather(GitHub("o", "r", run=fake_gh_runner), fake_git_runner,
                      "main")

    def test_gathers_closed_issues(self):
        ev = self._gather('{"reviews":[]}')
        self.assertTrue(ev.issues[2].closed)
        self.assertFalse(ev.issues[1].closed)

    def test_fetches_reviews_so_revisions_can_trigger(self):
        ev = self._gather(json.dumps({"reviews": [
            {"state": "CHANGES_REQUESTED", "submittedAt": "2024-06-01T00:00:00Z"},
            {"state": "COMMENTED", "submittedAt": "2024-07-01T00:00:00Z"},
        ]}))
        pr = ev.open_prs[1][0]
        self.assertEqual(pr.last_change_request_at, "2024-06-01T00:00:00Z")
        self.assertTrue(pr.has_unaddressed_changes)


class TestGatherAgainstRealGit(unittest.TestCase):
    """Drives real git with the daemon's real runner.

    Every other test here fakes the runner, which hid a double-`git` argv bug
    that made claim_refs and specs_landed silently empty in production for the
    daemon's entire life. Faked plumbing cannot catch plumbing mistakes.
    """

    def setUp(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from tests.helpers import add_origin, init_repo

        self.root = Path(tempfile.mkdtemp()) / "repo"
        self.root.mkdir()
        init_repo(self.root)
        add_origin(self.root)
        spec_dir = self.root / "docs" / "spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "42-a-feature.md").write_text("spec\n")
        (spec_dir / "notes.md").write_text("not a spec\n")
        for args in (["add", "-A"], ["commit", "-q", "-m", "spec"],
                     ["push", "-q", "origin", "main"],
                     ["push", "-q", "origin",
                      "main:refs/heads/meeseeks/impl/42-a-feature"],
                     ["push", "-q", "origin", "main:refs/heads/feature/other"],
                     ["fetch", "-q", "origin"]):
            subprocess.run(["git", "-C", str(self.root), *args], check=True)

    def _runner(self, args):
        import subprocess
        proc = subprocess.run(["git", "-C", str(self.root), *args],
                              capture_output=True, text=True)
        return proc.returncode == 0, proc.stdout

    def _gather(self):
        from orchestrator.github import GitHub

        def gh_runner(args, input=None):
            return True, "[]"

        return gather(GitHub("o", "r", run=gh_runner), self._runner,
                      "origin/main")

    def test_finds_landed_specs(self):
        self.assertIn(42, self._gather().specs_landed)

    def test_finds_claim_refs_and_ignores_foreign_branches(self):
        ev = self._gather()
        self.assertEqual(ev.claim_refs, {42: {"impl"}})


if __name__ == "__main__":
    unittest.main()
