"""Install root and project root discovery.

Everything the program ships is addressed from the install root.
Everything the project owns is addressed from the project root.
This module is the only place either root is resolved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

CONFIG_DIR = ".meeseeks"
CONFIG_FILE = "config.json"
RULES_FILE = "rules.md"
WORKTREES_DIR = ".worktrees"

INSTALL_ROOT = Path(__file__).resolve().parents[1]  # the agents/ directory
PROMPTS_DIR = INSTALL_ROOT / "prompts"


class ConfigNotFound(Exception):
    """No `.meeseeks/config.json` found after searching all roots."""


@dataclass(frozen=True)
class Paths:
    """Project-root derived paths. Picklable, so it can cross a Process boundary."""
    root: Path

    @property
    def config(self) -> Path:
        return self.root / CONFIG_DIR / CONFIG_FILE

    @property
    def rules(self) -> Path:
        return self.root / CONFIG_DIR / RULES_FILE

    @property
    def logs(self) -> Path:
        return self.root / CONFIG_DIR / "logs"

    @property
    def ledger(self) -> Path:
        return self.root / CONFIG_DIR / "state" / "claims.json"

    @property
    def worktrees(self) -> Path:
        return self.root / WORKTREES_DIR

    @property
    def is_git_repo(self) -> bool:
        return (self.root / ".git").exists()


def _has_marker(path: Path) -> bool:
    return (path / CONFIG_DIR / CONFIG_FILE).is_file()


def _walk_up(start: Path) -> Path | None:
    current = start.resolve()
    for parent in [current, *current.parents]:
        if _has_marker(parent):
            return parent
    return None


def find_root(
    start: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Find the project root by `.meeseeks/config.json` marker.

    Resolution order:
    1. ``MEESEEKS_ROOT`` from *env* — a missing marker under it is a hard error.
    2. Walk up from *start* (default ``cwd()``).
    3. Walk up from ``INSTALL_ROOT``.
    """
    env = os.environ if env is None else env
    start = Path.cwd() if start is None else start

    explicit = env.get("MEESEEKS_ROOT")
    if explicit is not None:
        root = Path(explicit)
        if _has_marker(root):
            return root
        raise ConfigNotFound(
            f"MEESEEKS_ROOT={explicit!r} set, but "
            f"{CONFIG_DIR}/{CONFIG_FILE} not found there"
        )

    found = _walk_up(start)
    if found is not None:
        return found

    found = _walk_up(INSTALL_ROOT)
    if found is not None:
        return found

    raise ConfigNotFound(
        f"no {CONFIG_DIR}/{CONFIG_FILE} found in "
        f"cwd ({start}) or install root ({INSTALL_ROOT}); "
        f"set MEESEEKS_ROOT to override"
    )


def rules_text(paths: Paths) -> str:
    """Contents of the project's rules file, or empty string if absent."""
    try:
        return paths.rules.read_text()
    except FileNotFoundError:
        return ""
