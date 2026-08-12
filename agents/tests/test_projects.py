from __future__ import annotations

import json
import unittest

from orchestrator.github import GitHub, GitHubError
from orchestrator.projects import Board, load_board, item_status, set_status


def _fake_runner(responses: list[tuple[bool, str]]):
    calls: list[tuple[list[str], str | None]] = []

    def runner(args: list[str], input: str | None = None) -> tuple[bool, str]:
        calls.append((args, input))
        return responses.pop(0)

    return runner, calls


class TestExplain(unittest.TestCase):
    def test_unknown_owner_type_names_the_missing_scope(self):
        from orchestrator.projects import explain
        out = explain("unknown owner type")
        self.assertIn("read:org", out)

    def test_insufficient_scopes_gets_a_hint(self):
        from orchestrator.projects import explain
        self.assertIn("scopes", explain("INSUFFICIENT_SCOPES: nope"))

    def test_other_errors_pass_through(self):
        from orchestrator.projects import explain
        self.assertEqual(explain("connection reset"), "connection reset")

    def test_load_board_surfaces_the_hint(self):
        runner, _ = _fake_runner([(False, "unknown owner type")])
        with self.assertRaises(GitHubError) as cm:
            load_board(GitHub("acme", "repo", run=runner), 1, "Status", [])
        self.assertIn("read:org", str(cm.exception))


class TestProjects(unittest.TestCase):
    def test_load_board_maps_options(self):
        runner, calls = _fake_runner([
            (
                True,
                json.dumps({
                    "fields": [
                        {
                            "name": "Status",
                            "id": "F_1",
                            "options": [
                                {"name": "Todo", "id": "O_1"},
                                {"name": "Done", "id": "O_2"},
                            ],
                        }
                    ],
                }),
            ),
            # field-list carries no project id; it comes from `project view`.
            (True, json.dumps({"id": "P_1", "number": 1})),
        ])
        gh = GitHub("acme", "repo", run=runner)
        board = load_board(gh, 1, "Status", ["Todo", "Done"])
        self.assertEqual(board.project_id, "P_1")
        self.assertEqual(board.status_field_id, "F_1")
        self.assertEqual(board.option_ids, {"Todo": "O_1", "Done": "O_2"})

    def test_load_board_missing_options_names_them(self):
        runner, calls = _fake_runner([(
            True,
            json.dumps({
                "id": "P_1",
                "fields": [
                    {
                        "name": "Status",
                        "id": "F_1",
                        "options": [
                            {"name": "Todo", "id": "O_1"},
                        ],
                    }
                ],
            }),
        )])
        gh = GitHub("acme", "repo", run=runner)
        with self.assertRaises(GitHubError) as cm:
            load_board(gh, 1, "Status", ["Todo", "Done"])
        self.assertIn("Done", str(cm.exception))

    def test_item_status(self):
        runner, calls = _fake_runner([(
            True,
            json.dumps({
                "items": [
                    {
                        "id": "I_1",
                        "content": {"number": 3},
                        "status": {"name": "Todo"},
                    },
                    {
                        "id": "I_2",
                        "content": {"number": 5},
                        "status": {"name": "Done"},
                    },
                ],
            }),
        )])
        gh = GitHub("acme", "repo", run=runner)
        result = item_status(gh, 1)
        self.assertEqual(result, {
            3: ("I_1", "Todo"),
            5: ("I_2", "Done"),
        })

    def test_item_status_skips_items_without_number(self):
        runner, calls = _fake_runner([(
            True,
            json.dumps({
                "items": [
                    {"id": "I_1", "content": {}, "status": {"name": "Todo"}},
                ],
            }),
        )])
        gh = GitHub("acme", "repo", run=runner)
        self.assertEqual(item_status(gh, 1), {})

    def test_set_status(self):
        runner, calls = _fake_runner([(True, "")])
        gh = GitHub("acme", "repo", run=runner)
        board = Board("P_1", "F_1", {"Todo": "O_1"})
        set_status(gh, board, "I_1", "Todo")
        self.assertIn("item-edit", calls[0][0])

    def test_set_status_unknown_option_raises(self):
        gh = GitHub("acme", "repo", run=lambda a, i=None: (True, ""))
        board = Board("P_1", "F_1", {})
        with self.assertRaises(GitHubError) as cm:
            set_status(gh, board, "I_1", "Todo")
        self.assertIn("Todo", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
