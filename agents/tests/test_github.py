from __future__ import annotations

import json
import unittest

from orchestrator.github import GitHub, GitHubError


def _capture() -> tuple[list, list]:
    calls: list[tuple[list[str], str | None]] = []
    responses: list[tuple[bool, str]] = []

    def runner(args: list[str], input: str | None = None) -> tuple[bool, str]:
        calls.append((args, input))
        return responses.pop(0)

    return runner, calls, responses


class TestGitHubAdapter(unittest.TestCase):
    def test_viewer_login(self):
        runner, calls, responses = _capture()
        responses.append((True, "alice\n"))
        gh = GitHub("acme", "repo", run=runner)
        self.assertEqual(gh.viewer_login(), "alice")
        self.assertEqual(calls[0][0], ["gh", "api", "user", "-q", ".login"])

    def test_viewer_login_error_raises(self):
        runner, calls, responses = _capture()
        responses.append((False, "boom"))
        gh = GitHub("acme", "repo", run=runner)
        with self.assertRaises(GitHubError):
            gh.viewer_login()

    def test_issues_with_label(self):
        runner, calls, responses = _capture()
        payload = [{"number": 1, "title": "a"}]
        responses.append((True, json.dumps(payload)))
        gh = GitHub("acme", "repo", run=runner)
        result = gh.issues_with_label("bug")
        self.assertEqual(result, payload)
        self.assertEqual(calls[0][0][:4], ["gh", "issue", "list", "--label"])
        self.assertEqual(calls[0][0][4], "bug")

    def test_issue(self):
        runner, calls, responses = _capture()
        payload = {"number": 7, "title": "t"}
        responses.append((True, json.dumps(payload)))
        gh = GitHub("acme", "repo", run=runner)
        self.assertEqual(gh.issue(7), payload)
        self.assertEqual(calls[0][0], [
            "gh", "issue", "view", "7",
            "--json", "number,title,body,labels,state,stateReason",
        ])

    def test_open_prs(self):
        runner, calls, responses = _capture()
        payload = [{"number": 3}]
        responses.append((True, json.dumps(payload)))
        gh = GitHub("acme", "repo", run=runner)
        self.assertEqual(gh.open_prs(), payload)
        self.assertIn("pr", calls[0][0])
        self.assertIn("list", calls[0][0])

    def test_merged_pr_branches(self):
        runner, calls, responses = _capture()
        payload = [{"number": 5, "headRefName": "x"}]
        responses.append((True, json.dumps(payload)))
        gh = GitHub("acme", "repo", run=runner)
        self.assertEqual(gh.merged_pr_branches(), payload)
        self.assertIn("--state", calls[0][0])
        self.assertIn("merged", calls[0][0])

    def test_pr_reviews(self):
        runner, calls, responses = _capture()
        payload = {"reviews": [{"state": "APPROVED"}]}
        responses.append((True, json.dumps(payload)))
        gh = GitHub("acme", "repo", run=runner)
        self.assertEqual(gh.pr_reviews(2), [{"state": "APPROVED"}])

    def test_pr_reviews_missing_key(self):
        runner, calls, responses = _capture()
        responses.append((True, "{}"))
        gh = GitHub("acme", "repo", run=runner)
        self.assertEqual(gh.pr_reviews(2), [])

    def test_pr_head_committed_at(self):
        runner, calls, responses = _capture()
        responses.append((True, "2024-01-01T00:00:00Z\n"))
        gh = GitHub("acme", "repo", run=runner)
        self.assertEqual(gh.pr_head_committed_at(9), "2024-01-01T00:00:00Z")

    def test_pr_head_committed_at_error_returns_none(self):
        runner, calls, responses = _capture()
        responses.append((False, ""))
        gh = GitHub("acme", "repo", run=runner)
        self.assertIsNone(gh.pr_head_committed_at(9))

    def test_create_ref_success(self):
        runner, calls, responses = _capture()
        responses.append((True, ""))
        gh = GitHub("acme", "repo", run=runner)
        self.assertTrue(gh.create_ref("refs/heads/x", "abc123"))
        self.assertIn("git/refs", calls[0][0][-5])

    def test_create_ref_already_exists_returns_false(self):
        runner, calls, responses = _capture()
        responses.append((False, "Reference already exists"))
        gh = GitHub("acme", "repo", run=runner)
        self.assertFalse(gh.create_ref("refs/heads/x", "abc123"))

    def test_create_ref_other_error_raises(self):
        runner, calls, responses = _capture()
        responses.append((False, "bad credentials"))
        gh = GitHub("acme", "repo", run=runner)
        with self.assertRaises(GitHubError):
            gh.create_ref("refs/heads/x", "abc123")

    def test_delete_ref(self):
        runner, calls, responses = _capture()
        responses.append((True, ""))
        gh = GitHub("acme", "repo", run=runner)
        gh.delete_ref("refs/heads/x")
        self.assertEqual(calls[0][0][:3], ["gh", "api", "-X"])
        self.assertIn("DELETE", calls[0][0])

    def test_add_label(self):
        runner, calls, responses = _capture()
        responses.append((True, ""))
        gh = GitHub("acme", "repo", run=runner)
        gh.add_label(1, "bug")
        self.assertIn("--add-label", calls[0][0])

    def test_remove_label(self):
        runner, calls, responses = _capture()
        responses.append((True, ""))
        gh = GitHub("acme", "repo", run=runner)
        gh.remove_label(1, "bug")
        self.assertIn("--remove-label", calls[0][0])

    def test_comment(self):
        runner, calls, responses = _capture()
        responses.append((True, ""))
        gh = GitHub("acme", "repo", run=runner)
        gh.comment(1, "hi")
        self.assertEqual(calls[0][0][:3], ["gh", "issue", "comment"])
        self.assertEqual(calls[0][1], "hi")

    def test_set_issue_body(self):
        runner, calls, responses = _capture()
        responses.append((True, ""))
        gh = GitHub("acme", "repo", run=runner)
        gh.set_issue_body(1, "body")
        self.assertEqual(calls[0][0][:3], ["gh", "issue", "edit"])
        self.assertEqual(calls[0][1], "body")

    def test_create_pr(self):
        runner, calls, responses = _capture()
        responses.append((True, "http://pr/1\n"))
        gh = GitHub("acme", "repo", run=runner)
        result = gh.create_pr("feat", "title", "body", "alice")
        self.assertEqual(result["url"], "http://pr/1")
        self.assertEqual(calls[0][1], "body")


class TestDefaultRunner(unittest.TestCase):
    """The real runner, which every faked test necessarily skips."""

    def test_captures_stdout(self):
        from orchestrator.github import default_runner
        ok, out = default_runner(["echo", "hello"])
        self.assertTrue(ok)
        self.assertEqual(out.strip(), "hello")

    def test_folds_stderr_into_output(self):
        from orchestrator.github import default_runner
        ok, out = default_runner(
            ["sh", "-c", "echo already exists >&2; exit 1"])
        self.assertFalse(ok)
        self.assertIn("already exists", out)

    def test_passes_stdin(self):
        from orchestrator.github import default_runner
        ok, out = default_runner(["cat"], input="piped")
        self.assertTrue(ok)
        self.assertEqual(out.strip(), "piped")


if __name__ == "__main__":
    unittest.main()
