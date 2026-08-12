"""This machine's record of the claims it holds.

Deliberately local and deliberately dumb: it exists so a daemon can recover its
own orphans after a crash. It is never consulted for another machine's claims —
those are visible only as refs on the remote.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Claim:
    number: int
    kind: str
    branch: str
    pid: int
    started_at: str


def load(path: Path) -> dict[int, Claim]:
    """Every claim this machine believes it holds.

    A corrupt file is treated as empty rather than fatal: a daemon that cannot
    start because its bookkeeping is malformed is worse than one that re-derives
    state from the remote.
    """
    try:
        raw = json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    claims: dict[int, Claim] = {}
    for number, entry in raw.items():
        try:
            claims[int(number)] = Claim(number=int(number), **entry)
        except (TypeError, ValueError):
            continue
    return claims


def _write(path: Path, claims: dict[int, Claim]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        str(n): {k: v for k, v in asdict(c).items() if k != "number"}
        for n, c in claims.items()
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def record(path: Path, number: int, kind: str, branch: str,
           pid: int, started_at: str) -> None:
    claims = load(path)
    claims[number] = Claim(number=number, kind=kind, branch=branch,
                           pid=pid, started_at=started_at)
    _write(path, claims)


def forget(path: Path, number: int) -> None:
    claims = load(path)
    if claims.pop(number, None) is not None:
        _write(path, claims)
