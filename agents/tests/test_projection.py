from __future__ import annotations

import unittest

from orchestrator.evidence import Evidence, IssueEv, PullEv
from orchestrator.projection import desired_column


def _ev(**kwargs) -> Evidence:
    defaults = {
        "issues": {},
        "open_prs": {},
        "claim_refs": {},
        "specs_landed": set(),
        "impl_merged": set(),
    }
    defaults.update(kwargs)
    return Evidence(**defaults)


class TestDesiredColumn(unittest.TestCase):
    def setUp(self):
        self.cols = {
            "done": "Done",
            "blocked": "Blocked",
            "in_progress": "In Progress",
            "in_review": "In Review",
            "ready": "Ready",
            "spec_review": "Spec Review",
            "backlog": "Backlog",
        }

    # Row 1: closed or impl merged -> done
    def test_closed_issue_is_done(self):
        ev = _ev(issues={1: IssueEv(1, "t", "b", frozenset(), True)})
        self.assertEqual(desired_column(1, ev, self.cols), "Done")

    def test_impl_merged_is_done(self):
        ev = _ev(impl_merged={1})
        self.assertEqual(desired_column(1, ev, self.cols), "Done")

    # Row 2: failed / blocked label -> blocked
    def test_failed_label_is_blocked(self):
        ev = _ev(issues={
            1: IssueEv(1, "t", "b", frozenset(["meeseeks:failed"]), False),
        })
        self.assertEqual(desired_column(1, ev, self.cols), "Blocked")

    def test_blocked_label_is_blocked(self):
        ev = _ev(issues={
            1: IssueEv(1, "t", "b", frozenset(["meeseeks:blocked"]), False),
        })
        self.assertEqual(desired_column(1, ev, self.cols), "Blocked")

    # Row 3: open impl PR with unaddressed changes -> in_progress
    def test_impl_pr_with_changes_is_in_progress(self):
        ev = _ev(open_prs={1: [PullEv(
            number=1, kind="impl", issue=1, branch="b",
            head_sha="s", mergeable=None,
            head_committed_at="2024-01-01T00:00:00Z",
            last_change_request_at="2024-01-02T00:00:00Z",
        )]})
        self.assertEqual(desired_column(1, ev, self.cols), "In Progress")

    # Row 4: open impl PR -> in_review
    def test_open_impl_pr_is_in_review(self):
        ev = _ev(open_prs={1: [PullEv(
            number=1, kind="impl", issue=1, branch="b",
            head_sha="s", mergeable=None,
            head_committed_at="2024-01-01T00:00:00Z",
            last_change_request_at=None,
        )]})
        self.assertEqual(desired_column(1, ev, self.cols), "In Review")

    # Row 5: impl claim -> in_progress
    def test_impl_claim_is_in_progress(self):
        ev = _ev(claim_refs={1: {"impl"}})
        self.assertEqual(desired_column(1, ev, self.cols), "In Progress")

    # Row 6: spec landed -> ready
    def test_spec_landed_is_ready(self):
        ev = _ev(specs_landed={1})
        self.assertEqual(desired_column(1, ev, self.cols), "Ready")

    # Row 7: open spec PR -> spec_review
    def test_open_spec_pr_is_spec_review(self):
        ev = _ev(open_prs={1: [PullEv(
            number=1, kind="spec", issue=1, branch="b",
            head_sha="s", mergeable=None,
            head_committed_at=None,
            last_change_request_at=None,
        )]})
        self.assertEqual(desired_column(1, ev, self.cols), "Spec Review")

    # Row 8: otherwise -> backlog
    def test_default_is_backlog(self):
        ev = _ev()
        self.assertEqual(desired_column(1, ev, self.cols), "Backlog")

    # Precedence tests
    def test_closed_with_failed_label_is_done(self):
        ev = _ev(issues={
            1: IssueEv(1, "t", "b", frozenset(["meeseeks:failed"]), True),
        })
        self.assertEqual(desired_column(1, ev, self.cols), "Done")

    def test_landed_spec_with_open_spec_pr_is_ready(self):
        ev = _ev(
            specs_landed={1},
            open_prs={1: [PullEv(
                number=1, kind="spec", issue=1, branch="b",
                head_sha="s", mergeable=None,
                head_committed_at=None,
                last_change_request_at=None,
            )]},
        )
        self.assertEqual(desired_column(1, ev, self.cols), "Ready")

    def test_impl_claim_with_landed_spec_is_in_progress(self):
        ev = _ev(
            claim_refs={1: {"impl"}},
            specs_landed={1},
        )
        self.assertEqual(desired_column(1, ev, self.cols), "In Progress")

    def test_impl_pr_with_change_requests_is_in_progress_not_in_review(self):
        ev = _ev(open_prs={1: [PullEv(
            number=1, kind="impl", issue=1, branch="b",
            head_sha="s", mergeable=None,
            head_committed_at="2024-01-01T00:00:00Z",
            last_change_request_at="2024-01-02T00:00:00Z",
        )]})
        self.assertEqual(desired_column(1, ev, self.cols), "In Progress")


if __name__ == "__main__":
    unittest.main()
