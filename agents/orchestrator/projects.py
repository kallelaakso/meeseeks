from __future__ import annotations

import json
from dataclasses import dataclass

from orchestrator.github import GitHub, GitHubError


def project_id(gh: GitHub, project_number: int) -> str:
    """The project's node id, needed for item-edit.

    `field-list` does not carry it — its only top-level keys are `fields` and
    `totalCount` — so it has to come from `project view`.
    """
    ok, out = gh.run([
        "gh", "project", "view", str(project_number),
        "--owner", gh.owner,
        "--format", "json",
    ])
    if not ok:
        raise GitHubError(f"project view failed: {out}")
    return json.loads(out)["id"]


@dataclass(frozen=True)
class Board:
    project_id: str
    status_field_id: str
    option_ids: dict[str, str]


def load_board(
    gh: GitHub,
    project_number: int,
    status_field: str,
    required_options: list[str],
) -> Board:
    ok, out = gh.run([
        "gh", "project", "field-list", str(project_number),
        "--owner", gh.owner,
        "--format", "json",
    ])
    if not ok:
        raise GitHubError(f"field-list failed: {out}")
    data = json.loads(out)
    fields = {f["name"]: f for f in data.get("fields", [])}
    field = fields.get(status_field)
    if field is None:
        raise GitHubError(f"status field {status_field!r} not found")
    options = {o["name"]: o["id"] for o in field.get("options", [])}
    missing = [o for o in required_options if o not in options]
    if missing:
        raise GitHubError(
            f"missing board options: {', '.join(missing)}"
        )
    return Board(
        project_id=project_id(gh, project_number),
        status_field_id=field["id"],
        option_ids=options,
    )


def item_status(
    gh: GitHub,
    project_number: int,
) -> dict[int, tuple[str, str]]:
    ok, out = gh.run([
        "gh", "project", "item-list", str(project_number),
        "--owner", gh.owner,
        "--format", "json",
    ])
    if not ok:
        raise GitHubError(f"item-list failed: {out}")
    data = json.loads(out)
    result: dict[int, tuple[str, str]] = {}
    for item in data.get("items", []):
        content = item.get("content", {})
        number = content.get("number")
        if number is None:
            continue
        # gh renders a single-select value as a bare string; older/other
        # shapes use {"name": ...}. Accept both rather than guess.
        status = item.get("status") or ""
        name = status.get("name", "") if isinstance(status, dict) else status
        result[number] = (item["id"], name)
    return result


def set_status(
    gh: GitHub,
    board: Board,
    item_id: str,
    option_name: str,
) -> None:
    option_id = board.option_ids.get(option_name)
    if option_id is None:
        raise GitHubError(f"unknown option {option_name!r}")
    ok, out = gh.run([
        "gh", "project", "item-edit",
        "--id", item_id,
        "--field-id", board.status_field_id,
        "--project-id", board.project_id,
        "--single-select-option-id", option_id,
    ])
    if not ok:
        raise GitHubError(f"item-edit failed: {out}")
