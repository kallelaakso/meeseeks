"""One unit of agent work, for either kind: worktree → agent → commit → PR.

Spec and impl runs differ only in which command runs, whether verify gates the
result, and what the PR says. Everything else — isolation, committing on the
agent's behalf, idempotent PR creation — is identical, so it lives here once.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator.config import Config
from orchestrator.fsops import append_log
from orchestrator.github import GitHub
from orchestrator.paths import PROMPTS_DIR, Paths, rules_text
from orchestrator.tickets import plan_path, spec_path
from orchestrator.worktree import create_worktree_on

PROMPT_FILE = ".meeseeks-prompt.md"

OPENED = "opened"
FAILED = "failed"
EMPTY = "empty"


def render_prompt(template: str, **tokens: str) -> str:
    """Substitute {name} tokens without str.format.

    Issue bodies routinely contain braces (code, JSON), which would make
    str.format raise or mangle them.
    """
    out = template
    for key, value in tokens.items():
        out = out.replace("{" + key + "}", value)
    return out


def _run(cmd: list[str] | str, cwd: Path, shell: bool = False) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), shell=shell,
                          capture_output=True, text=True)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def _commit(wt: Path, message: str, base_ref: str, log_path: Path) -> bool:
    """Commit whatever the agent left. True if the branch has work over base."""
    _run(["git", "add", "-A"], cwd=wt)
    staged_clean, _ = _run(["git", "diff", "--cached", "--quiet"], cwd=wt)
    if not staged_clean:
        ok, out = _run(["git", "commit", "-m", message], cwd=wt)
        if not ok:
            append_log(log_path, f"commit failed: {out}")
            return False
    ok, out = _run(["git", "rev-list", "--count", f"{base_ref}..HEAD"], cwd=wt)
    return ok and out.strip() not in ("", "0")


def _run_agent(command: str, wt: Path, log_path: Path) -> bool:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    append_log(log_path, f"running agent in {wt}: {command}")
    with log_path.open("a") as log:
        proc = subprocess.run(command, cwd=str(wt), shell=True,
                              stdout=log, stderr=subprocess.STDOUT, text=True)
    append_log(log_path, f"agent exited with code {proc.returncode}")
    return proc.returncode == 0


def pr_text(kind: str, number: int, title: str) -> tuple[str, str]:
    """PR title and body. Only impl PRs close the issue — a merged spec leaves
    the ticket half-done."""
    if kind == "spec":
        return (f"[spec] {title}",
                f"Spec and plan for #{number}.\n\nRefs #{number}\n")
    return (title, f"Implements the plan for #{number}.\n\nCloses #{number}\n")


def run_job(kind: str, number: int, slug: str, title: str, body: str,
            branch: str, cfg: Config, gh: GitHub, repo: Path,
            log_path: Path, feedback: str = "",
            prompts_dir: Path = PROMPTS_DIR) -> str:
    """Run one job to completion. Returns OPENED, FAILED or EMPTY."""
    worktrees = repo / ".worktrees"
    base_ref = f"{cfg.remote}/{cfg.base_branch}"
    name = f"{number}-{slug}"

    try:
        wt = create_worktree_on(repo, worktrees, name, branch, cfg.remote)
    except subprocess.CalledProcessError as exc:
        append_log(log_path, f"worktree setup failed: {exc}")
        return FAILED

    template = (prompts_dir / f"{kind}.md").read_text()
    prompt = render_prompt(
        template,
        issue=str(number), title=title, body=body, slug=slug,
        spec_path=spec_path(number, slug), plan_path=plan_path(number, slug),
        branch=branch, worktree=str(wt),
        verify_command=cfg.verify_command, feedback=feedback,
        project_rules=rules_text(Paths(repo)),
    )
    prompt_path = wt / PROMPT_FILE
    prompt_path.write_text(prompt)

    command = cfg.agent_command(kind).replace("{prompt_file}", PROMPT_FILE)
    agent_ok = _run_agent(command, wt, log_path)
    prompt_path.unlink(missing_ok=True)

    if not agent_ok:
        append_log(log_path, "agent exited non-zero")
        return FAILED
    if not _commit(wt, f"{kind} #{number}: {title}", base_ref, log_path):
        append_log(log_path, "agent produced no commits")
        return EMPTY

    if kind == "impl":
        ok, out = _run(cfg.verify_command, cwd=wt, shell=True)
        if not ok:
            append_log(log_path, f"verify failed: {out}")
            return FAILED

    ok, out = _run(["git", "push", "-u", cfg.remote, branch], cwd=wt)
    if not ok:
        append_log(log_path, f"push failed: {out}")
        return FAILED

    if gh.open_pr_for(branch) is None:
        pr_title, pr_body = pr_text(kind, number, title)
        gh.create_pr(branch, pr_title, pr_body, cfg.reviewer)
        append_log(log_path, f"opened {kind} PR for #{number}")
    else:
        append_log(log_path, f"PR already open for {branch}")
    return OPENED
