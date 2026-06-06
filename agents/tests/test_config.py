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


if __name__ == "__main__":
    unittest.main()
