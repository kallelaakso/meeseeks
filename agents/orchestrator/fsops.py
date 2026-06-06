from __future__ import annotations

from pathlib import Path


def move_into(src: Path, dest_dir: Path) -> Path:
    """Move src into dest_dir, keeping its filename. Returns the new path."""
    dest = dest_dir / src.name
    src.rename(dest)
    return dest


def append_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as log:
        log.write(f"[orchestrator] {message}\n")
