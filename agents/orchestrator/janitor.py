"""Maintenance of work already in flight.

Everything here is idempotent and safe to run on every poll, because the daemon
has no memory between cycles — it re-derives what needs doing from evidence.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator import claiming, ledger, tickets
from orchestrator.config import Config
from orchestrator.evidence import Evidence, PullEv
from orchestrator.fsops import append_log
from orchestrator.github import GitHub
from orchestrator.worktree import remove_worktree

LOG_TAIL_LINES = 60
LOG_TAIL_BYTES = 8000


def log_tail(log_path: Path) -> str:
    """The last few lines of a log, small enough for a comment."""
    try:
        lines = Path(log_path).read_text().splitlines()
    except FileNotFoundError:
        return "(no log)"
    tail = "\n".join(lines[-LOG_TAIL_LINES:])
    return tail[-LOG_TAIL_BYTES:]


def fail(gh: GitHub, cfg: Config, number: int, reason: str,
         branch: str, log_path: Path) -> None:
    """Mark a ticket failed and publish why.

    The comment is the whole point: a log that exists only on the machine that
    failed is useless to everyone else on the team.
    """
    body = (
        f"❌ **{reason}**\n\n"
        f"Branch: `{branch}`\n\n"
        f"<details><summary>log tail</summary>\n\n```\n"
        f"{log_tail(log_path)}\n```\n\n</details>\n\n"
        f"Remove the `{cfg.labels['failed']}` label to retry from scratch."
    )
    gh.comment(number, body)
    gh.add_label(number, cfg.labels["failed"])


def revision_tasks(ev: Evidence, cfg: Config) -> list[PullEv]:
    """PRs with unaddressed change requests, still under the attempt cap."""
    return [p for prs in ev.open_prs.values() for p in prs
            if p.has_unaddressed_changes
            and p.change_requests <= cfg.max_revision_attempts]


def cap_exceeded(ev: Evidence, cfg: Config) -> list[PullEv]:
    """PRs the agent has failed to satisfy too many times.

    Rounds of review are the proxy for attempts: each `CHANGES_REQUESTED` is
    one round the agent did not resolve. Past the cap it would loop forever,
    burning tokens on every poll.
    """
    return [p for prs in ev.open_prs.values() for p in prs
            if p.has_unaddressed_changes
            and p.change_requests > cfg.max_revision_attempts]


def block_capped(gh: GitHub, cfg: Config, prs: list[PullEv]) -> list[int]:
    blocked = []
    for pr in prs:
        gh.comment(
            pr.issue,
            f"🛑 Giving up after {pr.change_requests} rounds of review on "
            f"#{pr.number}. Take it from here, or remove the "
            f"`{cfg.labels['blocked']}` label to let the agent retry.",
        )
        gh.add_label(pr.issue, cfg.labels["blocked"])
        blocked.append(pr.issue)
    return blocked


def conflicting(ev: Evidence) -> list[PullEv]:
    """Only genuinely unmergeable PRs. A merely-behind PR is left alone —
    GitHub merges it cleanly, and force-pushing would orphan review threads."""
    return [p for prs in ev.open_prs.values() for p in prs
            if p.mergeable == "CONFLICTING"]


def rebase(repo: Path, worktree: Path, cfg: Config,
           log_path: Path) -> bool:
    """Rebase a conflicting PR onto base and re-verify. True if it worked."""
    def run(cmd, shell=False):
        proc = subprocess.run(cmd, cwd=str(worktree), shell=shell,
                              capture_output=True, text=True)
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()

    base = f"{cfg.remote}/{cfg.base_branch}"
    run(["git", "fetch", cfg.remote, cfg.base_branch])
    ok, out = run(["git", "rebase", base])
    if not ok:
        run(["git", "rebase", "--abort"])
        append_log(log_path, f"rebase onto {base} conflicted: {out}")
        return False
    # A clean rebase can still be semantically wrong, so verify again.
    ok, out = run(cfg.verify_command, shell=True)
    if not ok:
        append_log(log_path, f"verify failed after rebase: {out}")
        return False
    ok, out = run(["git", "push", "--force-with-lease"])
    if not ok:
        append_log(log_path, f"force-push after rebase failed: {out}")
        return False
    append_log(log_path, f"rebased onto {base} and force-pushed")
    return True


def publish_artifacts(gh: GitHub, cfg: Config, ev: Evidence) -> list[int]:
    """Put spec/plan links in the issue body once its spec has landed.

    Cosmetic by design — nothing depends on the block existing or being
    well-formed, so a human mangling it costs nothing.
    """
    updated = []
    for number in sorted(ev.specs_landed):
        issue = ev.issues.get(number)
        if issue is None or issue.closed:
            continue
        slug = tickets.slugify(issue.title)
        block = tickets.render_artifacts_block(
            tickets.spec_path(number, slug),
            tickets.plan_path(number, slug),
            number, cfg.repo_url,
        )
        body = tickets.upsert_artifacts_block(issue.body, block)
        if body != issue.body:
            gh.set_issue_body(number, body)
            updated.append(number)
    return updated


def disarm(gh: GitHub, cfg: Config, ev: Evidence) -> list[int]:
    """Drop the arm label once spec work exists for an issue.

    The label means "needs a spec", not "has one". Leaving it on makes the spec
    queue return the issue forever: the daemon re-claims it every poll, and
    would rewrite an already-merged spec the moment the claim cleared.
    """
    disarmed = []
    for number, issue in sorted(ev.issues.items()):
        if cfg.labels["arm"] not in issue.labels:
            continue
        has_spec_work = (
            number in ev.specs_landed
            or any(p.kind == "spec" for p in ev.open_prs.get(number, []))
        )
        if not has_spec_work:
            continue
        gh.remove_label(number, cfg.labels["arm"])
        disarmed.append(number)
    return disarmed


def release_finished_claims(gh: GitHub, cfg: Config, ev: Evidence,
                            repo: Path, ledger_path: Path) -> list[int]:
    """Drop our own claims whose work is over, and clean up their worktrees.

    Only claims in this machine's ledger are touched: another machine's stale
    claim is not ours to judge, and `release.py` is the deliberate escape hatch
    for that.
    """
    released = []
    for number, claim in ledger.load(ledger_path).items():
        finished = (
            number in ev.impl_merged
            or (claim.kind == "spec" and number in ev.specs_landed)
        )
        if not finished:
            continue
        claiming.release(gh, ledger_path, number, claim.branch)
        try:
            remove_worktree(repo, repo / ".worktrees"
                            / claim.branch.split("/", 2)[-1])
        except subprocess.CalledProcessError:
            pass
        released.append(number)
    return released
