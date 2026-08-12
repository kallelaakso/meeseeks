from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.config import Config, load_config

VALID = {
    "owner": "acme",
    "repo": "widgets",
    "project_number": 3,
    "bot_login": "acme-bot",
    "reviewer": "human",
    "spec_agent_command": "spec {prompt_file}",
    "impl_agent_command": "impl {prompt_file}",
    "verify_command": "true",
}


def write(data: dict) -> Path:
    path = Path(tempfile.mkdtemp()) / "config.json"
    path.write_text(json.dumps(data))
    return path


class TestLoadConfig(unittest.TestCase):
    def test_loads_valid(self):
        cfg = load_config(write(VALID))
        self.assertEqual(cfg.owner, "acme")
        self.assertEqual(cfg.poll_interval_seconds, 30)
        self.assertEqual(cfg.status_field, "Status")

    def test_rejects_missing_key(self):
        data = dict(VALID)
        del data["owner"]
        with self.assertRaises(ValueError) as cm:
            load_config(write(data))
        self.assertIn("owner", str(cm.exception))

    def test_rejects_unknown_key(self):
        with self.assertRaises(ValueError) as cm:
            load_config(write({**VALID, "integration_mode": "pr"}))
        self.assertIn("integration_mode", str(cm.exception))

    def test_defaults_fill_missing_column(self):
        columns = {k: k for k in ("backlog", "spec_review", "ready",
                                   "in_progress", "in_review", "blocked", "done")}
        del columns["blocked"]
        cfg = load_config(write({**VALID, "columns": columns}))
        self.assertEqual(cfg.columns["blocked"], "Blocked")

    def test_defaults_fill_missing_label(self):
        labels = {"arm": "arm", "failed": "failed", "blocked": "blocked"}
        del labels["arm"]
        cfg = load_config(write({**VALID, "labels": labels}))
        self.assertEqual(cfg.labels["arm"], "meeseeks:spec-me")

    def test_rejects_fast_poll(self):
        with self.assertRaises(ValueError):
            load_config(write({**VALID, "poll_interval_seconds": 1}))

    def test_rejects_zero_concurrency(self):
        with self.assertRaises(ValueError):
            load_config(write({**VALID, "max_impl_concurrency": 0}))

    def test_defaults_when_no_columns_or_labels(self):
        cfg = load_config(write(VALID))
        self.assertEqual(cfg.columns["done"], "Done")
        self.assertEqual(cfg.labels["arm"], "meeseeks:spec-me")
        self.assertEqual(cfg.base_branch, "main")

    def test_partial_column_override(self):
        cfg = load_config(write({**VALID, "columns": {"done": "Shipped"}}))
        self.assertEqual(cfg.columns["done"], "Shipped")
        self.assertEqual(cfg.columns["backlog"], "Backlog")

    def test_rejects_unknown_column_key(self):
        with self.assertRaises(ValueError) as cm:
            load_config(write({**VALID, "columns": {"backlogg": "Oops"}}))
        self.assertIn("backlogg", str(cm.exception))

    def test_rejects_unknown_label_key(self):
        with self.assertRaises(ValueError) as cm:
            load_config(write({**VALID, "labels": {"armm": "Oops"}}))
        self.assertIn("armm", str(cm.exception))


class TestConfigHelpers(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(write(VALID))

    def test_required_options_in_flow_order(self):
        self.assertEqual(self.cfg.required_options[0], "Backlog")
        self.assertEqual(self.cfg.required_options[-1], "Done")
        self.assertEqual(len(self.cfg.required_options), 7)

    def test_blocking_labels(self):
        self.assertEqual(self.cfg.blocking_labels,
                         ("meeseeks:failed", "meeseeks:blocked"))

    def test_agent_command_and_concurrency_by_kind(self):
        self.assertTrue(self.cfg.agent_command("spec").startswith("spec"))
        self.assertTrue(self.cfg.agent_command("impl").startswith("impl"))
        self.assertEqual(self.cfg.concurrency("spec"), 1)
        self.assertEqual(self.cfg.concurrency("impl"), 3)

    def test_repo_url(self):
        self.assertEqual(self.cfg.repo_url,
                         "https://github.com/acme/widgets")


class TestRealConfig(unittest.TestCase):
    def test_shipped_config_is_valid(self):
        repo = Path(__file__).resolve().parents[2]
        cfg = load_config(repo / ".meeseeks" / "config.json")
        self.assertIsInstance(cfg, Config)


if __name__ == "__main__":
    unittest.main()
