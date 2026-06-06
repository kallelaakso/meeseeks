from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dashboard.model import (
    InvalidPlan,
    PlanView,
    SpecView,
    rollup_spec_status,
    scan_plans,
    scan_specs,
)
from orchestrator.layout import Layout


class TestScanPlans(unittest.TestCase):
    def _plan(self, dir_: Path, name: str, body: str) -> Path:
        dir_.mkdir(parents=True, exist_ok=True)
        p = dir_ / name
        p.write_text(body)
        return p

    def test_basic_scan(self):
        root = Path(tempfile.mkdtemp())
        layout = Layout.under(root)
        self._plan(layout.ready, "a.md", "---\nid: alpha\ndepends-on: []\nspec: foo.md\n---\n")
        views, invalids = scan_plans(layout)
        self.assertEqual(len(views), 1)
        self.assertEqual(views["alpha"].id, "alpha")
        self.assertEqual(views["alpha"].state, "ready-for-work")
        self.assertEqual(views["alpha"].spec, "foo.md")
        self.assertEqual(invalids, [])

    def test_malformed_draft_collected_as_invalid(self):
        root = Path(tempfile.mkdtemp())
        layout = Layout.under(root)
        drafts = root / "docs" / "plan" / "drafts"
        self._plan(drafts, "bad.md", "no frontmatter\n")
        views, invalids = scan_plans(layout)
        self.assertEqual(views, {})
        self.assertEqual(len(invalids), 1)
        self.assertEqual(invalids[0].path.name, "bad.md")
        self.assertEqual(invalids[0].state, "drafts")

    def test_duplicate_id_prefers_non_drafts(self):
        root = Path(tempfile.mkdtemp())
        layout = Layout.under(root)
        drafts = root / "docs" / "plan" / "drafts"
        self._plan(drafts, "a.md", "---\nid: alpha\n---\n")
        self._plan(layout.ready, "a.md", "---\nid: alpha\n---\n")
        views, invalids = scan_plans(layout)
        self.assertEqual(views["alpha"].state, "ready-for-work")
        self.assertEqual(invalids, [])

    def test_duplicate_id_prefers_more_advanced(self):
        root = Path(tempfile.mkdtemp())
        layout = Layout.under(root)
        self._plan(layout.ready, "a.md", "---\nid: alpha\n---\n")
        self._plan(layout.in_progress, "a.md", "---\nid: alpha\n---\n")
        views, invalids = scan_plans(layout)
        self.assertEqual(views["alpha"].state, "in-progress")
        self.assertEqual(invalids, [])


class TestRollupSpecStatus(unittest.TestCase):
    def test_no_linked_plans(self):
        self.assertEqual(rollup_spec_status("foo.md", {}), "drafted")

    def test_any_in_progress(self):
        views = {
            "p1": PlanView("p1", "in-progress", [], "foo.md", Path("/p1"), "p1.md"),
            "p2": PlanView("p2", "ready-for-work", [], "foo.md", Path("/p2"), "p2.md"),
        }
        self.assertEqual(rollup_spec_status("foo.md", views), "in-progress")

    def test_any_ready_for_work(self):
        views = {
            "p1": PlanView("p1", "ready-for-work", [], "foo.md", Path("/p1"), "p1.md"),
            "p2": PlanView("p2", "done", [], "foo.md", Path("/p2"), "p2.md"),
        }
        self.assertEqual(rollup_spec_status("foo.md", views), "planned")

    def test_any_awaiting_merge(self):
        views = {
            "p1": PlanView("p1", "awaiting-merge", [], "foo.md", Path("/p1"), "p1.md"),
            "p2": PlanView("p2", "done", [], "foo.md", Path("/p2"), "p2.md"),
        }
        self.assertEqual(rollup_spec_status("foo.md", views), "in-review")

    def test_all_done(self):
        views = {
            "p1": PlanView("p1", "done", [], "foo.md", Path("/p1"), "p1.md"),
            "p2": PlanView("p2", "done", [], "foo.md", Path("/p2"), "p2.md"),
        }
        self.assertEqual(rollup_spec_status("foo.md", views), "done")

    def test_only_failed_closed(self):
        views = {
            "p1": PlanView("p1", "failed", [], "foo.md", Path("/p1"), "p1.md"),
            "p2": PlanView("p2", "closed", [], "foo.md", Path("/p2"), "p2.md"),
        }
        self.assertEqual(rollup_spec_status("foo.md", views), "blocked")

    def test_mixed_default(self):
        views = {
            "p1": PlanView("p1", "ready-for-work", [], "foo.md", Path("/p1"), "p1.md"),
            "p2": PlanView("p2", "done", [], "foo.md", Path("/p2"), "p2.md"),
        }
        self.assertEqual(rollup_spec_status("foo.md", views), "planned")


class TestScanSpecs(unittest.TestCase):
    def test_scan_specs_links_and_rollup(self):
        root = Path(tempfile.mkdtemp())
        layout = Layout.under(root)
        spec_dir = root / "docs" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "foo.md").write_text("# Foo\n")
        (spec_dir / "bar.md").write_text("# Bar\n")

        plan_views = {
            "p1": PlanView("p1", "in-progress", [], "foo.md", Path("/p1"), "p1.md"),
            "p2": PlanView("p2", "ready-for-work", [], "foo.md", Path("/p2"), "p2.md"),
        }
        specs = scan_specs(layout, plan_views)
        self.assertEqual(len(specs), 2)
        foo = next(s for s in specs if s.filename == "foo.md")
        self.assertEqual(foo.status, "in-progress")
        self.assertEqual(set(foo.linked_plan_ids), {"p1", "p2"})
        bar = next(s for s in specs if s.filename == "bar.md")
        self.assertEqual(bar.status, "drafted")
        self.assertEqual(bar.linked_plan_ids, [])


if __name__ == "__main__":
    unittest.main()
