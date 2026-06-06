from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_INLINE_LIST = re.compile(r"^\[(.*)\]$")


@dataclass(frozen=True)
class Plan:
    id: str
    depends_on: list[str]
    path: Path
    spec: str | None = None


def _parse_frontmatter(text: str) -> dict[str, str]:
    m = _FRONTMATTER.match(text)
    if not m:
        raise ValueError("plan has no leading --- frontmatter block")
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _parse_deps(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw or raw == "[]":
        return []
    m = _INLINE_LIST.match(raw)
    if not m:
        raise ValueError(f"depends-on must be an inline list like [a, b], got {raw!r}")
    return [item.strip() for item in m.group(1).split(",") if item.strip()]


def parse_plan(path: Path) -> Plan:
    fields = _parse_frontmatter(Path(path).read_text())
    if "id" not in fields or not fields["id"]:
        raise ValueError(f"plan {path} missing required 'id'")
    deps = _parse_deps(fields.get("depends-on", ""))
    return Plan(
        id=fields["id"], depends_on=deps, path=Path(path),
        spec=fields.get("spec") or None,
    )


def list_plans(directory: Path) -> list[Plan]:
    return [parse_plan(p) for p in sorted(Path(directory).glob("*.md"))]


def done_ids(done_dir: Path) -> set[str]:
    return {plan.id for plan in list_plans(done_dir)}


def eligible_plans(ready_dir: Path, done_dir: Path) -> list[Plan]:
    done = done_ids(done_dir)
    return [p for p in list_plans(ready_dir) if set(p.depends_on) <= done]
