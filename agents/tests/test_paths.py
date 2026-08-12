from __future__ import annotations

import os
import pickle
import tempfile
import unittest
from pathlib import Path

from orchestrator.paths import (
    ConfigNotFound,
    Paths,
    find_root,
    rules_text,
)


def _marker(root: Path) -> None:
    path = root / ".meeseeks" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")


class TestFindRoot(unittest.TestCase):
    def test_finds_marker_in_start_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            _marker(root)
            self.assertEqual(find_root(start=root), root)

    def test_finds_marker_several_levels_up(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            _marker(root)
            nested = root / "a" / "b" / "c"
            nested.mkdir(parents=True)
            self.assertEqual(find_root(start=nested), root)

    def test_meeseeks_root_wins(self):
        with tempfile.TemporaryDirectory() as td:
            root_a = Path(td) / "a"
            root_b = Path(td) / "b"
            _marker(root_a)
            _marker(root_b)
            env = {"MEESEEKS_ROOT": str(root_b)}
            self.assertEqual(find_root(start=root_a, env=env), root_b)

    def test_meeseeks_root_missing_marker_raises(self):
        with tempfile.TemporaryDirectory() as td:
            env = {"MEESEEKS_ROOT": str(td)}
            with self.assertRaises(ConfigNotFound) as cm:
                find_root(env=env)
            self.assertIn("MEESEEKS_ROOT", str(cm.exception))

    def test_no_marker_anywhere_raises(self):
        with tempfile.TemporaryDirectory() as td:
            env = {"MEESEEKS_ROOT": str(td)}
            with self.assertRaises(ConfigNotFound) as cm:
                find_root(env=env)
            self.assertIn("MEESEEKS_ROOT", str(cm.exception))


class TestPaths(unittest.TestCase):
    def test_properties(self):
        root = Path("/fake")
        p = Paths(root)
        self.assertEqual(p.config, root / ".meeseeks" / "config.json")
        self.assertEqual(p.rules, root / ".meeseeks" / "rules.md")
        self.assertEqual(p.logs, root / ".meeseeks" / "logs")
        self.assertEqual(p.ledger, root / ".meeseeks" / "state" / "claims.json")
        self.assertEqual(p.worktrees, root / ".worktrees")

    def test_is_git_repo_true(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").write_text("gitdir: / elsewhere")
            self.assertTrue(Paths(root).is_git_repo)

    def test_is_git_repo_false(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(Paths(Path(td)).is_git_repo)

    def test_pickle_roundtrip(self):
        p = Paths(Path("/some/root"))
        self.assertEqual(pickle.loads(pickle.dumps(p)), p)


class TestRulesText(unittest.TestCase):
    def test_returns_empty_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(rules_text(Paths(Path(td))), "")

    def test_returns_exact_text_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _marker(root)
            (root / ".meeseeks" / "rules.md").write_text("Use tabs.")
            self.assertEqual(rules_text(Paths(root)), "Use tabs.")


if __name__ == "__main__":
    unittest.main()
