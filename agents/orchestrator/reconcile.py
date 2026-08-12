"""Render the board from evidence.

The Status field is written, never read for decisions. Writes are convergent —
every daemon computes the same value from the same evidence — so concurrent
reconcilers cannot fight. A human dragging a card is overwritten on the next
poll, which is the intended behaviour: the card is a view, not a control.
"""

from __future__ import annotations

from orchestrator.config import Config
from orchestrator.evidence import Evidence
from orchestrator.github import GitHubError
from orchestrator.projection import desired_column
from orchestrator.projects import Board, item_status, set_status


def plan_moves(current: dict[int, tuple[str, str]], ev: Evidence,
               cfg: Config) -> list[tuple[int, str, str, str]]:
    """(issue, item_id, from, to) for every card in the wrong column."""
    moves = []
    for number, (item_id, now) in sorted(current.items()):
        want = desired_column(number, ev, cfg.columns, cfg.blocking_labels)
        if want != now:
            moves.append((number, item_id, now, want))
    return moves


def reconcile(gh, board: Board, ev: Evidence, cfg: Config,
              project_number: int) -> list[tuple[int, str, str]]:
    """Move any card that disagrees with the evidence. Never raises.

    The board lagging is an inconvenience; a board failure stopping the daemon
    would be an outage, so every Projects error is swallowed after logging.
    """
    try:
        current = item_status(gh, project_number)
    except (GitHubError, ValueError, KeyError):
        return []

    moved = []
    for number, item_id, was, want in plan_moves(current, ev, cfg):
        try:
            set_status(gh, board, item_id, want)
        except GitHubError:
            continue
        moved.append((number, was, want))
    return moved
