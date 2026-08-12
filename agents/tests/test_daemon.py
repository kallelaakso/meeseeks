from __future__ import annotations

import json
import unittest

import daemon
from orchestrator.config import Config
from orchestrator.github import GitHub


def _config(**overrides) -> Config:
    base = dict(
        owner="o", repo="r", project_number=1, bot_login="meeseeks-bot",
        reviewer="human", base_branch="main",
        spec_agent_command="true", impl_agent_command="true",
        verify_command="true",
        columns={k: k for k in ("backlog", "spec_review", "ready",
                                "in_progress", "in_review", "blocked", "done")},
        labels={"arm": "arm", "failed": "failed", "blocked": "blocked"},
    )
    base.update(overrides)
    return Config(**base)


class TestValidate(unittest.TestCase):
    def test_refuses_to_run_as_a_human(self):
        """Running under a human token silently kills the review loop, since
        GitHub forbids reviewing your own PR."""
        def runner(args, input=None):
            return True, "kallelaakso\n"

        with self.assertRaises(SystemExit) as cm:
            daemon.validate(GitHub("o", "r", run=runner), _config())
        self.assertIn("meeseeks-bot", str(cm.exception))

    def test_missing_column_is_fatal(self):
        def runner(args, input=None):
            if "user" in args:
                return True, "meeseeks-bot\n"
            if "field-list" in args:
                return True, json.dumps({"fields": [
                    {"name": "Status", "id": "F", "options": [
                        {"name": "backlog", "id": "O1"},
                    ]},
                ]})
            return True, "{}"

        with self.assertRaises(Exception) as cm:
            daemon.validate(GitHub("o", "r", run=runner), _config())
        self.assertIn("done", str(cm.exception))

    def test_accepts_a_correct_setup(self):
        options = [{"name": k, "id": f"O_{k}"} for k in
                   ("backlog", "spec_review", "ready", "in_progress",
                    "in_review", "blocked", "done")]

        def runner(args, input=None):
            if "user" in args:
                return True, "meeseeks-bot\n"
            if "field-list" in args:
                return True, json.dumps({"fields": [
                    {"name": "Status", "id": "F", "options": options},
                ]})
            return True, json.dumps({"id": "P_1"})

        board = daemon.validate(GitHub("o", "r", run=runner), _config())
        self.assertEqual(board.project_id, "P_1")


class TestFeedbackText(unittest.TestCase):
    def test_collects_only_change_requests(self):
        def runner(args, input=None):
            return True, json.dumps({"reviews": [
                {"state": "CHANGES_REQUESTED", "body": "fix the naming"},
                {"state": "COMMENTED", "body": "nice"},
                {"state": "CHANGES_REQUESTED", "body": "and the tests"},
            ]})

        text = daemon.feedback_text(GitHub("o", "r", run=runner), 7)
        self.assertIn("fix the naming", text)
        self.assertIn("and the tests", text)
        self.assertNotIn("nice", text)

    def test_no_change_requests_is_empty(self):
        def runner(args, input=None):
            return True, json.dumps({"reviews": []})

        self.assertEqual(daemon.feedback_text(GitHub("o", "r", run=runner), 7),
                         "")


if __name__ == "__main__":
    unittest.main()
