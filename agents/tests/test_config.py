from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.config import Config, load_config

VALID = {
    "max_concurrency": 2,
    "poll_interval_seconds": 5,
    "integration_mode": "auto-merge",
    "base_branch": "main",
    "verify_command": "true",
    "agent_command": "echo {plan_path}",
}


class TestConfig(unittest.TestCase):
    def _write(self, data: dict) -> Path:
        d = Path(tempfile.mkdtemp())
        p = d / "config.json"
        p.write_text(json.dumps(data))
        return p

    def test_loads_valid_config(self):
        cfg = load_config(self._write(VALID))
        self.assertEqual(cfg.max_concurrency, 2)
        self.assertEqual(cfg.integration_mode, "auto-merge")

    def test_rejects_unknown_integration_mode(self):
        bad = {**VALID, "integration_mode": "yolo"}
        with self.assertRaises(ValueError):
            load_config(self._write(bad))

    def test_rejects_missing_key(self):
        bad = {k: v for k, v in VALID.items() if k != "base_branch"}
        with self.assertRaises(ValueError):
            load_config(self._write(bad))

    def test_rejects_non_positive_concurrency(self):
        bad = {**VALID, "max_concurrency": 0}
        with self.assertRaises(ValueError):
            load_config(self._write(bad))

    def test_optional_merge_sweep_interval_defaults_to_300(self):
        cfg = load_config(self._write(VALID))
        self.assertEqual(cfg.merge_sweep_interval_seconds, 300)

    def test_explicit_merge_sweep_interval_is_honored(self):
        data = {**VALID, "merge_sweep_interval_seconds": 60}
        cfg = load_config(self._write(data))
        self.assertEqual(cfg.merge_sweep_interval_seconds, 60)

    def test_rejects_non_positive_merge_sweep_interval(self):
        bad = {**VALID, "merge_sweep_interval_seconds": 0}
        with self.assertRaises(ValueError):
            load_config(self._write(bad))

    def test_dashboard_defaults(self):
        cfg = load_config(self._write(VALID))
        self.assertEqual(cfg.dashboard_port, 8787)
        self.assertEqual(cfg.dashboard_poll_interval_seconds, 3.0)
        self.assertEqual(cfg.dashboard_pr_sweep_interval_seconds, 60.0)
        self.assertEqual(cfg.dashboard_db, "agents/dashboard.db")

    def test_dashboard_overrides(self):
        data = {
            **VALID,
            "dashboard_port": 8080,
            "dashboard_poll_interval_seconds": 5.0,
            "dashboard_pr_sweep_interval_seconds": 120.0,
            "dashboard_db": "agents/other.db",
        }
        cfg = load_config(self._write(data))
        self.assertEqual(cfg.dashboard_port, 8080)
        self.assertEqual(cfg.dashboard_poll_interval_seconds, 5.0)
        self.assertEqual(cfg.dashboard_pr_sweep_interval_seconds, 120.0)
        self.assertEqual(cfg.dashboard_db, "agents/other.db")

    def test_rejects_non_positive_dashboard_port(self):
        bad = {**VALID, "dashboard_port": 0}
        with self.assertRaises(ValueError):
            load_config(self._write(bad))

    def test_rejects_too_small_dashboard_poll_interval(self):
        bad = {**VALID, "dashboard_poll_interval_seconds": 0.05}
        with self.assertRaises(ValueError):
            load_config(self._write(bad))

    def test_agent_timeout_defaults_to_1800(self):
        cfg = load_config(self._write(VALID))
        self.assertEqual(cfg.agent_timeout_seconds, 1800)

    def test_explicit_agent_timeout_is_honored(self):
        cfg = load_config(self._write({**VALID, "agent_timeout_seconds": 60}))
        self.assertEqual(cfg.agent_timeout_seconds, 60)

    def test_zero_agent_timeout_allowed(self):
        cfg = load_config(self._write({**VALID, "agent_timeout_seconds": 0}))
        self.assertEqual(cfg.agent_timeout_seconds, 0)

    def test_rejects_negative_agent_timeout(self):
        with self.assertRaises(ValueError):
            load_config(self._write({**VALID, "agent_timeout_seconds": -1}))


if __name__ == "__main__":
    unittest.main()
