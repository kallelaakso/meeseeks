from __future__ import annotations

import re


_ARTIFACTS_START = "<!-- meeseeks:artifacts -->"
_ARTIFACTS_END = "<!-- /meeseeks:artifacts -->"


def slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    if len(s) > 40:
        s = s[:40].rsplit("-", 1)[0]
    return s


def branch(kind: str, number: int, slug: str) -> str:
    return f"meeseeks/{kind}/{number}-{slug}"


def parse_branch(ref: str) -> tuple[str, int] | None:
    m = re.match(r"^meeseeks/(spec|impl)/(\d+)-", ref)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def spec_path(number: int, slug: str) -> str:
    return f"docs/spec/{number}-{slug}.md"


def plan_path(number: int, slug: str) -> str:
    return f"docs/plan/{number}-{slug}.md"


def artifact_glob(number: int, directory: str) -> str:
    return f"docs/{directory}/{number}-*.md"


def parse_depends_on(body: str) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for line in body.splitlines():
        m = re.search(r"Depends\s+on\s*:?\s*(.+)", line, re.IGNORECASE)
        if not m:
            continue
        for num_str in re.findall(r"#(\d+)", m.group(1)):
            n = int(num_str)
            if n not in seen:
                seen.add(n)
                result.append(n)
    return result


def render_artifacts_block(spec: str, plan: str,
                           spec_pr: int, repo_url: str) -> str:
    lines = [
        _ARTIFACTS_START,
        f"- **Spec:** {spec}",
        f"- **Plan:** {plan}",
        f"- **Spec PR:** #{spec_pr} ({repo_url}/pull/{spec_pr})",
        _ARTIFACTS_END,
    ]
    return "\n".join(lines)


def upsert_artifacts_block(body: str, block: str) -> str:
    if _ARTIFACTS_START in body:
        pattern = re.compile(
            re.escape(_ARTIFACTS_START) + r".*?" + re.escape(_ARTIFACTS_END),
            re.DOTALL,
        )
        return pattern.sub(block, body)
    return body.rstrip("\n") + "\n\n" + block + "\n"
