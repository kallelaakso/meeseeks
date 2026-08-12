from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator import ledger
from orchestrator.config import Config
from orchestrator.evidence import Evidence, IssueEv
from orchestrator.github import GitHub
from orchestrator.projects import Board
from orchestrator.reconcile import plan_moves, reconcile
from orchestrator.recovery import recover, work_escaped

COLUMNS = {
    "backlog": "Backlog", "spec_review": "Spec in review",
    "ready": "Ready", "in_progress": "In progress",
    "in_review": "In review", "blocked": "Blocked", "done": "Done",
}


def _config(**overrides) -> Config:
    base = dict(
        owner="o", repo="r", project_number=1, bot_login="bot",
        reviewer="human", base_branch="main",
        spec_agent_command="true", impl_agent_command="true",
        verify_command="true", columns=COLUMNS,
        labels={"arm": "arm", "failed": "meeseeks:failed",
                "blocked": "meeseeks:blocked"},
    )
    base.update(overrides)
    return Config(**base)


def evidence(issues=(), specs_landed=(), impl_merged=()):
    return Evidence(issues={i.number: i for i in issues}, open_prs={},
                    claim_refs={}, specs_landed=set(specs_landed),
                    impl_merged=set(impl_merged))


BOARD = Board(project_id="P", status_field_id="F",
              option_ids={v: f"O_{v}" for v in COLUMNS.values()})


class TestPlanMoves(unittest.TestCase):
    def test_only_mismatched_cards_move(self):
        ev = evidence([IssueEv(1, "t", "", frozenset(), False),
                       IssueEv(2, "t", "", frozenset(), False)],
                      specs_landed=[2])
        current = {1: ("I1", "Backlog"), 2: ("I2", "Backlog")}
        moves = plan_moves(current, ev, _config())
        self.assertEqual([(m[0], m[3]) for m in moves], [(2, "Ready")])

    def test_agreeing_board_moves_nothing(self):
        ev = evidence([IssueEv(1, "t", "", frozenset(), False)])
        self.assertEqual(plan_moves({1: ("I1", "Backlog")}, ev, _config()), [])

    def test_uses_configured_label_names(self):
        ev = evidence([IssueEv(1, "t", "", frozenset({"meeseeks:failed"}),
                               False)])
        moves = plan_moves({1: ("I1", "Backlog")}, ev, _config())
        self.assertEqual(moves[0][3], "Blocked")


class TestReconcile(unittest.TestCase):
    def test_writes_only_differences(self):
        calls: list = []

        def runner(args, input=None):
            calls.append(args)
            if "item-list" in args:
                return True, json.dumps({"items": [
                    {"id": "I1", "status": "Backlog", "content": {"number": 1}},
                    {"id": "I2", "status": "Ready", "content": {"number": 2}},
                ]})
            return True, "{}"

        ev = evidence([IssueEv(1, "t", "", frozenset(), False),
                       IssueEv(2, "t", "", frozenset(), False)],
                      specs_landed=[2])
        moved = reconcile(GitHub("o", "r", run=runner), BOARD, ev, _config(), 1)
        self.assertEqual(moved, [])  # both already correct
        self.assertEqual([c for c in calls if "item-edit" in c], [])

    def test_moves_card_when_evidence_disagrees(self):
        calls: list = []

        def runner(args, input=None):
            calls.append(args)
            if "item-list" in args:
                return True, json.dumps({"items": [
                    {"id": "I1", "status": "Backlog", "content": {"number": 1}},
                ]})
            return True, "{}"

        ev = evidence([IssueEv(1, "t", "", frozenset(), False)],
                      specs_landed=[1])
        moved = reconcile(GitHub("o", "r", run=runner), BOARD, ev, _config(), 1)
        self.assertEqual(moved, [(1, "Backlog", "Ready")])
        self.assertTrue([c for c in calls if "item-edit" in c])

    def test_board_failure_is_swallowed(self):
        def runner(args, input=None):
            return False, "boom"

        ev = evidence([IssueEv(1, "t", "", frozenset(), False)])
        self.assertEqual(
            reconcile(GitHub("o", "r", run=runner), BOARD, ev, _config(), 1),
            [],
        )

    def test_bare_string_status_is_understood(self):
        """gh renders single-select values as plain strings."""
        def runner(args, input=None):
            if "item-list" in args:
                return True, json.dumps({"items": [
                    {"id": "I1", "status": "Done", "content": {"number": 1}},
                ]})
            return True, "{}"

        ev = evidence([IssueEv(1, "t", "", frozenset(), True)])
        self.assertEqual(
            reconcile(GitHub("o", "r", run=runner), BOARD, ev, _config(), 1),
            [],
        )


class TestRecovery(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "claims.json"
        self.logs = Path(tempfile.mkdtemp())

    def test_zero_commit_branch_is_released_not_failed(self):
        """The bug that dead-ended plan 1: a claim branch with no commits sits
        at base and must be retried, not sent to triage."""
        ledger.record(self.path, 1, "impl", "meeseeks/impl/1-x", 1, "T")

        def git(args):
            if "rev-list" in args:
                return True, "0"
            return True, ""

        out = recover(GitHub("o", "r", run=lambda *a, **k: (True, "{}")),
                      _config(), Path("/repo"), self.path, self.logs, git)
        self.assertEqual(out, {1: "released"})
        self.assertEqual(ledger.load(self.path), {})

    def test_escaped_work_is_failed_for_triage(self):
        ledger.record(self.path, 1, "impl", "meeseeks/impl/1-x", 1, "T")

        def git(args):
            if "rev-list" in args:
                return True, "3"
            return True, ""

        out = recover(GitHub("o", "r", run=lambda *a, **k: (True, "{}")),
                      _config(), Path("/repo"), self.path, self.logs, git)
        self.assertEqual(out, {1: "failed"})
        self.assertEqual(ledger.load(self.path), {})

    def test_satisfied_spec_claim_is_released_not_failed(self):
        """A leftover branch from a superseded PR looks like escaped work.

        If the spec already landed the ticket is finished, and flagging it
        strands it in Blocked — which is exactly what happened to issue #9.
        """
        ledger.record(self.path, 9, "spec", "meeseeks/spec/9-x", 1, "T")

        def git(args):
            if "ls-tree" in args:
                return True, "docs/spec/9-top-level.md\n"
            if "rev-list" in args:
                return True, "1"      # unmerged commits exist on the branch
            return True, ""

        out = recover(GitHub("o", "r", run=lambda *a, **k: (True, "{}")),
                      _config(), Path("/repo"), self.path, self.logs, git)
        self.assertEqual(out, {9: "released"})

    def test_unsatisfied_spec_claim_with_escaped_work_still_fails(self):
        ledger.record(self.path, 9, "spec", "meeseeks/spec/9-x", 1, "T")

        def git(args):
            if "ls-tree" in args:
                return True, "docs/spec/1-other.md\n"
            if "rev-list" in args:
                return True, "1"
            return True, ""

        out = recover(GitHub("o", "r", run=lambda *a, **k: (True, "{}")),
                      _config(), Path("/repo"), self.path, self.logs, git)
        self.assertEqual(out, {9: "failed"})

    def test_work_escaped_is_false_when_fetch_fails(self):
        self.assertFalse(work_escaped(lambda args: (False, "no such ref"),
                                      _config(), "b"))


if __name__ == "__main__":
    unittest.main()
