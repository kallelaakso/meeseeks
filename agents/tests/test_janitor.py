from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator import ledger
from orchestrator.config import Config
from orchestrator.evidence import Evidence, IssueEv, PullEv
from orchestrator.github import GitHub
from orchestrator.janitor import (
    block_capped,
    disarm,
    cap_exceeded,
    conflicting,
    fail,
    log_tail,
    publish_artifacts,
    release_finished_claims,
    revision_tasks,
)


def _config(**overrides) -> Config:
    base = dict(
        owner="o", repo="r", project_number=1, bot_login="bot",
        reviewer="human", base_branch="main",
        spec_agent_command="true", impl_agent_command="true",
        verify_command="true",
        columns={k: k for k in ("backlog", "spec_review", "ready",
                                "in_progress", "in_review", "blocked", "done")},
        labels={"arm": "arm", "failed": "meeseeks:failed",
                "blocked": "meeseeks:blocked"},
    )
    base.update(overrides)
    return Config(**base)


def _gh(calls: list, payload: str = "[]") -> GitHub:
    def runner(args, input=None):
        calls.append((args, input))
        return True, payload

    return GitHub("o", "r", run=runner)


def pull(number=10, kind="impl", issue=1, mergeable="MERGEABLE",
         requested=None, committed=None, count=0):
    return PullEv(number=number, kind=kind, issue=issue,
                  branch=f"meeseeks/{kind}/{issue}-x", head_sha="a",
                  mergeable=mergeable, head_committed_at=committed,
                  last_change_request_at=requested, change_requests=count)


def evidence(issues=(), open_prs=None, specs_landed=(), impl_merged=()):
    return Evidence(issues={i.number: i for i in issues},
                    open_prs=open_prs or {}, claim_refs={},
                    specs_landed=set(specs_landed),
                    impl_merged=set(impl_merged))


class TestFail(unittest.TestCase):
    def test_comments_with_log_tail_then_labels(self):
        log = Path(tempfile.mkdtemp()) / "1.log"
        log.write_text("\n".join(f"line {i}" for i in range(200)))
        calls: list = []
        fail(_gh(calls), _config(), 1, "verify failed", "b", log)

        bodies = [c[1] for c in calls if c[1]]
        self.assertIn("verify failed", bodies[0])
        self.assertIn("line 199", bodies[0])
        self.assertNotIn("line 100", bodies[0])  # truncated to the tail
        self.assertTrue(any("--add-label" in c[0] for c in calls))

    def test_missing_log_does_not_raise(self):
        self.assertEqual(log_tail(Path("/nope/nope.log")), "(no log)")


class TestRevisions(unittest.TestCase):
    def setUp(self):
        self.cfg = _config(max_revision_attempts=3)

    def _ev(self, count):
        return evidence(open_prs={1: [pull(requested="2024-02-01",
                                           committed="2024-01-01",
                                           count=count)]})

    def test_under_cap_is_a_revision_task(self):
        self.assertEqual(len(revision_tasks(self._ev(1), self.cfg)), 1)
        self.assertEqual(cap_exceeded(self._ev(1), self.cfg), [])

    def test_at_cap_still_gets_one_more_try(self):
        self.assertEqual(len(revision_tasks(self._ev(3), self.cfg)), 1)

    def test_over_cap_is_blocked_not_retried(self):
        self.assertEqual(revision_tasks(self._ev(4), self.cfg), [])
        self.assertEqual(len(cap_exceeded(self._ev(4), self.cfg)), 1)

    def test_addressed_feedback_is_not_a_task(self):
        ev = evidence(open_prs={1: [pull(requested="2024-01-01",
                                         committed="2024-02-01", count=1)]})
        self.assertEqual(revision_tasks(ev, self.cfg), [])

    def test_block_capped_labels_and_comments(self):
        calls: list = []
        blocked = block_capped(_gh(calls), self.cfg, [pull(count=4)])
        self.assertEqual(blocked, [1])
        self.assertTrue(any("--add-label" in c[0] for c in calls))


class TestConflicting(unittest.TestCase):
    def test_only_conflicting_prs(self):
        ev = evidence(open_prs={
            1: [pull(issue=1, mergeable="MERGEABLE")],
            2: [pull(number=11, issue=2, mergeable="CONFLICTING")],
        })
        self.assertEqual([p.issue for p in conflicting(ev)], [2])

    def test_behind_but_mergeable_is_left_alone(self):
        ev = evidence(open_prs={1: [pull(mergeable="MERGEABLE")]})
        self.assertEqual(conflicting(ev), [])


class TestPublishArtifacts(unittest.TestCase):
    def test_adds_block_once_and_is_idempotent(self):
        issue = IssueEv(1, "Add OAuth", "Original body", frozenset(), False)
        calls: list = []
        gh = _gh(calls)
        updated = publish_artifacts(gh, _config(), evidence([issue],
                                                            specs_landed=[1]))
        self.assertEqual(updated, [1])
        new_body = calls[0][1]
        self.assertIn("docs/spec/1-add-oauth.md", new_body)
        self.assertIn("Original body", new_body)

        # Re-running against the updated body writes nothing.
        issue2 = IssueEv(1, "Add OAuth", new_body, frozenset(), False)
        calls2: list = []
        publish_artifacts(_gh(calls2), _config(),
                          evidence([issue2], specs_landed=[1]))
        self.assertEqual(calls2, [])

    def test_skips_issues_without_landed_specs(self):
        issue = IssueEv(1, "T", "b", frozenset(), False)
        calls: list = []
        publish_artifacts(_gh(calls), _config(), evidence([issue]))
        self.assertEqual(calls, [])


class TestDisarm(unittest.TestCase):
    """The arm label means 'needs a spec', not 'has one'."""

    def _issue(self, labels=("arm",)):
        return IssueEv(1, "T", "b", frozenset(labels), False)

    def test_removes_label_once_spec_pr_is_open(self):
        calls: list = []
        ev = evidence([self._issue()],
                      open_prs={1: [pull(kind="spec")]})
        self.assertEqual(disarm(_gh(calls), _config(), ev), [1])
        self.assertTrue(any("--remove-label" in c[0] for c in calls))

    def test_removes_label_once_spec_landed(self):
        ev = evidence([self._issue()], specs_landed=[1])
        self.assertEqual(disarm(_gh([]), _config(), ev), [1])

    def test_keeps_label_while_no_spec_work_exists(self):
        calls: list = []
        self.assertEqual(disarm(_gh(calls), _config(),
                                evidence([self._issue()])), [])
        self.assertEqual(calls, [])

    def test_ignores_unarmed_issues(self):
        ev = evidence([self._issue(labels=())], specs_landed=[1])
        self.assertEqual(disarm(_gh([]), _config(), ev), [])


class TestReleaseFinishedClaims(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "claims.json"
        self.repo = Path(tempfile.mkdtemp())

    def test_releases_claim_once_impl_merged(self):
        ledger.record(self.path, 1, "impl", "meeseeks/impl/1-x", 1, "T")
        calls: list = []
        released = release_finished_claims(_gh(calls), _config(),
                                           evidence(impl_merged=[1]),
                                           self.repo, self.path)
        self.assertEqual(released, [1])
        self.assertEqual(ledger.load(self.path), {})

    def test_releases_spec_claim_once_spec_landed(self):
        ledger.record(self.path, 1, "spec", "meeseeks/spec/1-x", 1, "T")
        released = release_finished_claims(_gh([]), _config(),
                                           evidence(specs_landed=[1]),
                                           self.repo, self.path)
        self.assertEqual(released, [1])

    def test_keeps_claims_still_in_flight(self):
        ledger.record(self.path, 1, "impl", "meeseeks/impl/1-x", 1, "T")
        released = release_finished_claims(_gh([]), _config(), evidence(),
                                           self.repo, self.path)
        self.assertEqual(released, [])
        self.assertIn(1, ledger.load(self.path))


if __name__ == "__main__":
    unittest.main()
