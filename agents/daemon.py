"""The meeseeks daemon: watch GitHub, run agents, render the board.

State lives in GitHub — labels, pull requests, refs, files on the base branch.
Every cycle re-derives what to do from that evidence, so the daemon has no
memory to corrupt and a crash costs nothing but time.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from multiprocessing import Process
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator import claiming, janitor, queues, tickets
from orchestrator.config import Config, load_config
from orchestrator.evidence import Evidence, gather, GitRunner
from orchestrator.github import GitHub, GitHubError
from orchestrator.job import run_job
from orchestrator.paths import ConfigNotFound, Paths, find_root
from orchestrator.projects import Board, load_board
from orchestrator.reconcile import reconcile
from orchestrator.recovery import recover


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_git(root: Path) -> GitRunner:
    def git(args: list[str]) -> tuple[bool, str]:
        proc = subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True)
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()

    return git


def base_sha(cfg: Config, git: GitRunner) -> str:
    git(["fetch", cfg.remote, cfg.base_branch])
    ok, out = git(["rev-parse", f"{cfg.remote}/{cfg.base_branch}"])
    if not ok:
        raise GitHubError(f"cannot resolve {cfg.remote}/{cfg.base_branch}")
    return out.strip()


def validate(gh: GitHub, cfg: Config, paths: Paths) -> Board:
    """Refuse to start on a misconfigured setup.

    The bot-login check is the important one: running under a human token makes
    every PR unreviewable by that human, since GitHub forbids reviewing your
    own PR — the review loop would be silently dead.
    """
    if not paths.is_git_repo:
        raise SystemExit(
            f"refusing to start: {paths.root} is not a git repository"
        )
    login = gh.viewer_login()
    if login != cfg.bot_login:
        raise SystemExit(
            f"refusing to run as {login!r}: config expects the bot account "
            f"{cfg.bot_login!r}. GitHub forbids reviewing your own PRs, so "
            f"running as a human breaks the review loop. Set GH_TOKEN to the "
            f"bot's token."
        )
    return load_board(gh, cfg.project_number, cfg.status_field,
                      cfg.required_options)


def feedback_text(gh: GitHub, pr_number: int) -> str:
    """The change requests an agent must address, as prompt text."""
    bodies = [r.get("body", "").strip() for r in gh.pr_reviews(pr_number)
              if r.get("state") == "CHANGES_REQUESTED"]
    bodies = [b for b in bodies if b]
    if not bodies:
        return ""
    joined = "\n\n---\n\n".join(bodies)
    return ("# Requested changes\n\nA reviewer asked for these changes. "
            f"Address them:\n\n{joined}\n")


def _work(kind: str, number: int, slug: str, title: str, body: str,
          branch: str, cfg: Config, paths: Paths, feedback: str) -> None:
    """Child-process entrypoint: run one job, report failure to the issue."""
    gh = GitHub(cfg.owner, cfg.repo)
    log_path = paths.logs / f"{number}.log"
    try:
        outcome = run_job(kind, number, slug, title, body, branch, cfg, gh,
                          paths.root, log_path, feedback)
    except Exception as exc:  # noqa: BLE001 — a crash must still be visible
        janitor.fail(gh, cfg, number, f"{kind} run crashed: {exc}",
                     branch, log_path)
        raise SystemExit(1)
    if outcome != "opened":
        janitor.fail(gh, cfg, number, f"{kind} run {outcome}", branch,
                     log_path)
        raise SystemExit(1)


def spawn(kind: str, number: int, slug: str, title: str, body: str,
          branch: str, cfg: Config, paths: Paths,
          feedback: str = "") -> Process:
    proc = Process(target=_work, name=f"{kind}-{number}",
                   args=(kind, number, slug, title, body, branch, cfg,
                         paths, feedback))
    proc.start()
    print(f"daemon: started {kind} for #{number}")
    return proc


def _issue(ev: Evidence, number: int):
    return ev.issues[number]


def fill(kind: str, eligible: list[int], ev: Evidence, cfg: Config,
         gh: GitHub, running: dict[int, Process], paths: Paths) -> None:
    """Claim and start work up to this kind's concurrency limit."""
    active = sum(1 for p in running.values() if p.name.startswith(kind))
    git = make_git(paths.root)
    for number in eligible:
        if active >= cfg.concurrency(kind) or number in running:
            break
        issue = _issue(ev, number)
        slug = tickets.slugify(issue.title)
        branch = claiming.claim(gh, paths.ledger, kind, number, slug,
                                base_sha(cfg, git), now())
        if branch is None:
            print(f"daemon: #{number} claimed elsewhere")
            continue
        running[number] = spawn(kind, number, slug, issue.title, issue.body,
                                branch, cfg, paths)
        active += 1


def poll_once(gh: GitHub, board: Board, cfg: Config,
              running: dict[int, Process], paths: Paths) -> None:
    for number in [n for n, p in running.items() if not p.is_alive()]:
        proc = running.pop(number)
        proc.join()
        print(f"daemon: #{number} finished (exit {proc.exitcode})")

    # Evidence includes "which spec files exist on base", read from the local
    # remote-tracking ref. Without a fetch first that ref is whatever it was at
    # startup, so every merge stays invisible until something else refreshes it.
    git = make_git(paths.root)
    git(["fetch", cfg.remote, cfg.base_branch])

    ev = gather(gh, git, f"{cfg.remote}/{cfg.base_branch}",
                remote=cfg.remote)

    # Evidence is a snapshot: an issue disarmed now still carries the label in
    # `ev`, so it must be excluded explicitly or it is queued one last time.
    disarmed = set(janitor.disarm(gh, cfg, ev))
    janitor.block_capped(gh, cfg, janitor.cap_exceeded(ev, cfg))
    janitor.publish_artifacts(gh, cfg, ev)
    janitor.release_finished_claims(gh, cfg, ev, paths.root, paths.ledger)

    for pr in janitor.conflicting(ev):
        worktree = paths.worktrees / pr.branch.split("/", 2)[-1]
        if worktree.exists():
            janitor.rebase(paths.root, worktree, cfg,
                           paths.logs / f"{pr.issue}.log")

    for pr in janitor.revision_tasks(ev, cfg):
        if pr.issue in running:
            continue
        issue = ev.issues.get(pr.issue)
        if issue is None:
            continue
        running[pr.issue] = spawn(
            pr.kind, pr.issue, tickets.slugify(issue.title), issue.title,
            issue.body, pr.branch, cfg, paths, feedback_text(gh, pr.number),
        )

    armed = [n for n in queues.spec_queue(ev, cfg.labels)
             if n not in disarmed]
    fill("spec", armed, ev, cfg, gh, running, paths)
    fill("impl", queues.impl_queue(ev, cfg.labels), ev, cfg, gh, running, paths)

    for number, was, want in reconcile(gh, board, ev, cfg, cfg.project_number):
        print(f"daemon: board #{number} {was} -> {want}")


def main() -> int:
    try:
        paths = Paths(find_root())
    except ConfigNotFound as exc:
        print(f"daemon: {exc}")
        return 2
    cfg = load_config(paths.config)
    gh = GitHub(cfg.owner, cfg.repo)
    board = validate(gh, cfg, paths)

    for number, outcome in recover(gh, cfg, paths.root, paths.ledger,
                                   paths.logs).items():
        print(f"daemon: recovered #{number} -> {outcome}")

    running: dict[int, Process] = {}
    print(f"daemon: project root {paths.root}")
    print(f"daemon: polling {cfg.owner}/{cfg.repo} every "
          f"{cfg.poll_interval_seconds}s "
          f"(spec={cfg.max_spec_concurrency}, impl={cfg.max_impl_concurrency})")
    try:
        while True:
            try:
                poll_once(gh, board, cfg, running, paths)
            except GitHubError as exc:
                print(f"daemon: github error, backing off: {exc}")
            time.sleep(cfg.poll_interval_seconds)
    except KeyboardInterrupt:
        print("daemon: shutting down, waiting for workers...")
        for proc in running.values():
            proc.join()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
