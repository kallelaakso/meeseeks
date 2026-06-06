from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.layout import Layout
from orchestrator.plans import Plan, parse_plan, list_plans, done_ids, eligible_plans


class TestLayout(unittest.TestCase):
    def test_under_builds_expected_paths(self):
        root = Path("/tmp/example")
        layout = Layout.under(root)
        self.assertEqual(layout.ready, root / "docs" / "plan" / "ready-for-work")
        self.assertEqual(layout.in_progress, root / "docs" / "plan" / "in-progress")
        self.assertEqual(layout.awaiting_merge, root / "docs" / "plan" / "awaiting-merge")
        self.assertEqual(layout.done, root / "docs" / "plan" / "done")
        self.assertEqual(layout.closed, root / "docs" / "plan" / "closed")
        self.assertEqual(layout.failed, root / "docs" / "plan" / "failed")
        self.assertEqual(layout.worktrees, root / ".worktrees")
        self.assertEqual(layout.logs, root / "agents" / "logs")
        self.assertEqual(layout.repo, root)


class TestPlans(unittest.TestCase):
    def _plan(self, dir_: Path, name: str, body: str) -> Path:
        dir_.mkdir(parents=True, exist_ok=True)
        p = dir_ / name
        p.write_text(body)
        return p

    def test_parse_id_and_deps(self):
        d = Path(tempfile.mkdtemp())
        p = self._plan(d, "a.md", "---\nid: alpha\ndepends-on: [beta, gamma]\n---\nbody\n")
        plan = parse_plan(p)
        self.assertEqual(plan.id, "alpha")
        self.assertEqual(plan.depends_on, ["beta", "gamma"])
        self.assertEqual(plan.path, p)

    def test_parse_missing_deps_defaults_empty(self):
        d = Path(tempfile.mkdtemp())
        p = self._plan(d, "a.md", "---\nid: alpha\n---\nbody\n")
        self.assertEqual(parse_plan(p).depends_on, [])

    def test_parse_missing_id_raises(self):
        d = Path(tempfile.mkdtemp())
        p = self._plan(d, "a.md", "---\ndepends-on: []\n---\nbody\n")
        with self.assertRaises(ValueError):
            parse_plan(p)

    def test_parse_no_frontmatter_raises(self):
        d = Path(tempfile.mkdtemp())
        p = self._plan(d, "a.md", "no frontmatter here\n")
        with self.assertRaises(ValueError):
            parse_plan(p)

    def test_parse_spec_present(self):
        d = Path(tempfile.mkdtemp())
        p = self._plan(d, "a.md", "---\nid: alpha\nspec: foo-design.md\n---\nbody\n")
        self.assertEqual(parse_plan(p).spec, "foo-design.md")

    def test_parse_spec_missing(self):
        d = Path(tempfile.mkdtemp())
        p = self._plan(d, "a.md", "---\nid: alpha\n---\nbody\n")
        self.assertIsNone(parse_plan(p).spec)

    def test_eligible_only_when_deps_done(self):
        root = Path(tempfile.mkdtemp())
        ready = root / "ready"
        done = root / "done"
        self._plan(ready, "a.md", "---\nid: alpha\ndepends-on: [beta]\n---\n")
        self._plan(ready, "b.md", "---\nid: delta\n---\n")
        elig = {p.id for p in eligible_plans(ready, done)}
        self.assertEqual(elig, {"delta"})
        self._plan(done, "beta.md", "---\nid: beta\n---\n")
        elig = {p.id for p in eligible_plans(ready, done)}
        self.assertEqual(elig, {"delta", "alpha"})


if __name__ == "__main__":
    unittest.main()
