from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator import ledger
from orchestrator.claiming import claim, release
from orchestrator.github import GitHub, GitHubError


def _runner(script):
    calls: list[list[str]] = []

    def runner(args: list[str], input: str | None = None) -> tuple[bool, str]:
        calls.append(args)
        return script(args)

    return runner, calls


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "state" / "claims.json"

    def test_round_trip(self):
        ledger.record(self.path, 42, "impl", "meeseeks/impl/42-x", 7, "T")
        claims = ledger.load(self.path)
        self.assertEqual(claims[42].kind, "impl")
        self.assertEqual(claims[42].pid, 7)
        self.assertEqual(claims[42].number, 42)

    def test_forget(self):
        ledger.record(self.path, 42, "impl", "b", 7, "T")
        ledger.forget(self.path, 42)
        self.assertEqual(ledger.load(self.path), {})

    def test_forget_missing_is_noop(self):
        ledger.forget(self.path, 99)  # must not raise

    def test_missing_file_is_empty(self):
        self.assertEqual(ledger.load(self.path), {})

    def test_corrupt_file_is_empty_not_fatal(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json")
        self.assertEqual(ledger.load(self.path), {})

    def test_write_leaves_no_tmp_file(self):
        ledger.record(self.path, 1, "spec", "b", 1, "T")
        leftovers = list(self.path.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])


class TestClaim(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "claims.json"

    def test_winner_records_and_comments(self):
        def script(args):
            if "git/refs" in " ".join(args):
                return True, "{}"
            return True, ""

        runner, calls = _runner(script)
        gh = GitHub("o", "r", run=runner)
        branch = claim(gh, self.path, "impl", 42, "slug", "abc", "NOW",
                       host="box")

        self.assertEqual(branch, "meeseeks/impl/42-slug")
        self.assertEqual(ledger.load(self.path)[42].branch, branch)
        commented = [c for c in calls if "comment" in c]
        self.assertEqual(len(commented), 1)

    def test_loser_claims_nothing(self):
        def script(args):
            if "git/refs" in " ".join(args):
                return False, "Reference already exists"
            return True, ""

        runner, calls = _runner(script)
        gh = GitHub("o", "r", run=runner)
        branch = claim(gh, self.path, "impl", 42, "slug", "abc", "NOW")

        self.assertIsNone(branch)
        self.assertEqual(ledger.load(self.path), {})
        self.assertEqual([c for c in calls if "comment" in c], [])

    def test_api_error_is_not_a_lost_race(self):
        def script(args):
            return False, "HTTP 401: Bad credentials"

        runner, _ = _runner(script)
        gh = GitHub("o", "r", run=runner)
        with self.assertRaises(GitHubError):
            claim(gh, self.path, "impl", 42, "slug", "abc", "NOW")

    def test_release_is_idempotent(self):
        ledger.record(self.path, 42, "impl", "meeseeks/impl/42-slug", 1, "T")

        def script(args):
            return False, "Reference does not exist"

        runner, _ = _runner(script)
        gh = GitHub("o", "r", run=runner)
        release(gh, self.path, 42, "meeseeks/impl/42-slug")
        release(gh, self.path, 42, "meeseeks/impl/42-slug")
        self.assertEqual(ledger.load(self.path), {})


if __name__ == "__main__":
    unittest.main()
