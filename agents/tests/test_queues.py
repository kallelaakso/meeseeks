from __future__ import annotations

import unittest

from orchestrator.evidence import Evidence, IssueEv, PullEv
from orchestrator.queues import (
    dependency_cycles,
    impl_queue,
    spec_queue,
    unmet_dependencies,
)

LABELS = {"arm": "meeseeks:spec-me", "failed": "meeseeks:failed",
          "blocked": "meeseeks:blocked"}


def issue(number, body="", labels=(), closed=False):
    return IssueEv(number=number, title=f"issue {number}", body=body,
                   labels=frozenset(labels), closed=closed)


def pull(number, kind, issue_number):
    return PullEv(number=number, kind=kind, issue=issue_number,
                  branch=f"meeseeks/{kind}/{issue_number}-x", head_sha="a",
                  mergeable="MERGEABLE", head_committed_at=None,
                  last_change_request_at=None)


def evidence(issues=(), open_prs=None, claim_refs=None,
             specs_landed=(), impl_merged=()):
    return Evidence(
        issues={i.number: i for i in issues},
        open_prs=open_prs or {},
        claim_refs=claim_refs or {},
        specs_landed=set(specs_landed),
        impl_merged=set(impl_merged),
    )


class TestSpecQueue(unittest.TestCase):
    def test_armed_issue_is_queued(self):
        ev = evidence([issue(1, labels=["meeseeks:spec-me"])])
        self.assertEqual(spec_queue(ev, LABELS), [1])

    def test_unarmed_issue_is_not_queued(self):
        self.assertEqual(spec_queue(evidence([issue(1)]), LABELS), [])

    def test_closed_issue_is_never_queued(self):
        ev = evidence([issue(1, labels=["meeseeks:spec-me"], closed=True)])
        self.assertEqual(spec_queue(ev, LABELS), [])

    def test_failed_label_suppresses(self):
        ev = evidence([issue(1, labels=["meeseeks:spec-me",
                                        "meeseeks:failed"])])
        self.assertEqual(spec_queue(ev, LABELS), [])

    def test_existing_claim_suppresses(self):
        ev = evidence([issue(1, labels=["meeseeks:spec-me"])],
                      claim_refs={1: {"spec"}})
        self.assertEqual(spec_queue(ev, LABELS), [])

    def test_landed_spec_suppresses(self):
        """A stale arm label must not send the agent back over merged work."""
        ev = evidence([issue(1, labels=["meeseeks:spec-me"])],
                      specs_landed=[1])
        self.assertEqual(spec_queue(ev, LABELS), [])

    def test_open_spec_pr_suppresses(self):
        ev = evidence([issue(1, labels=["meeseeks:spec-me"])],
                      open_prs={1: [pull(10, "spec", 1)]})
        self.assertEqual(spec_queue(ev, LABELS), [])


class TestImplQueue(unittest.TestCase):
    def test_landed_spec_is_queued(self):
        ev = evidence([issue(1)], specs_landed=[1])
        self.assertEqual(impl_queue(ev, LABELS), [1])

    def test_unlanded_spec_is_not_queued(self):
        self.assertEqual(impl_queue(evidence([issue(1)]), LABELS), [])

    def test_already_merged_is_not_requeued(self):
        ev = evidence([issue(1)], specs_landed=[1], impl_merged=[1])
        self.assertEqual(impl_queue(ev, LABELS), [])

    def test_open_impl_pr_suppresses(self):
        ev = evidence([issue(1)], specs_landed=[1],
                      open_prs={1: [pull(10, "impl", 1)]})
        self.assertEqual(impl_queue(ev, LABELS), [])

    def test_unmerged_dependency_gates(self):
        ev = evidence([issue(1, body="Depends on: #2"), issue(2)],
                      specs_landed=[1, 2])
        self.assertEqual(impl_queue(ev, LABELS), [2])

    def test_merged_dependency_releases(self):
        ev = evidence([issue(1, body="Depends on: #2"), issue(2)],
                      specs_landed=[1], impl_merged=[2])
        self.assertEqual(impl_queue(ev, LABELS), [1])

    def test_unmet_dependencies_lists_them(self):
        ev = evidence([issue(1, body="Depends on: #2, #3")], impl_merged=[2])
        self.assertEqual(unmet_dependencies(ev, 1), [3])


class TestDependencyCycles(unittest.TestCase):
    def test_two_node_cycle(self):
        ev = evidence([issue(1, body="Depends on: #2"),
                       issue(2, body="Depends on: #1")])
        cycles = dependency_cycles(ev)
        self.assertEqual(len(cycles), 1)
        self.assertEqual(set(cycles[0]), {1, 2})

    def test_self_dependency(self):
        ev = evidence([issue(1, body="Depends on: #1")])
        self.assertEqual([set(c) for c in dependency_cycles(ev)], [{1}])

    def test_acyclic_graph_has_no_cycles(self):
        ev = evidence([issue(1, body="Depends on: #2"),
                       issue(2, body="Depends on: #3"), issue(3)])
        self.assertEqual(dependency_cycles(ev), [])


if __name__ == "__main__":
    unittest.main()
