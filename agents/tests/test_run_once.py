from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from tests.helpers import init_repo, make_layout
from orchestrator.config import Config

# Import run_once.py (not a package module) by path.
_SPEC = importlib.util.spec_from_file_location(
    "run_once", Path(__file__).resolve().parents[1] / "run_once.py")
run_once = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(run_once)

_DSPEC = importlib.util.spec_from_file_location(
    "daemon", Path(__file__).resolve().parents[1] / "daemon.py")
daemon = importlib.util.module_from_spec(_DSPEC)
_DSPEC.loader.exec_module(daemon)


def _cfg(agent: str) -> Config:
    return Config(1, 1, "auto-merge", "main", "true", agent)


class TestRunOnce(unittest.TestCase):
    def test_runs_first_eligible_plan(self):
        root = Path(tempfile.mkdtemp())
        init_repo(root)
        layout = make_layout(root)
        (layout.ready / "p.md").write_text("---\nid: feat\n---\ngo\n")
        agent = "bash -c 'echo hi > OUT.txt && git add -A && git commit -q -m w'"
        result = run_once.run_next(layout, _cfg(agent))
        self.assertEqual(result, "done")
        self.assertTrue((layout.done / "p.md").exists())

    def test_returns_none_when_no_eligible_plan(self):
        root = Path(tempfile.mkdtemp())
        init_repo(root)
        layout = make_layout(root)
        (layout.ready / "p.md").write_text("---\nid: feat\ndepends-on: [missing]\n---\n")
        result = run_once.run_next(layout, _cfg("true"))
        self.assertIsNone(result)

    def test_poll_once_respects_concurrency_cap(self):
        root = Path(tempfile.mkdtemp())
        init_repo(root)
        layout = make_layout(root)
        for i in range(3):
            (layout.ready / f"p{i}.md").write_text(f"---\nid: feat{i}\n---\n")
        cfg = Config(2, 1, "auto-merge", "main", "true",
                     "bash -c 'sleep 2'")  # long-running so they stay alive
        running: dict = {}
        daemon.poll_once(layout, cfg, running)
        self.assertEqual(len(running), 2)  # capped at max_concurrency
        for proc in running.values():
            proc.terminate()
            proc.join()


if __name__ == "__main__":
    unittest.main()
