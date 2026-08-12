from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
