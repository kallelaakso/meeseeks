# The orchestrator

A daemon that turns GitHub issues into pull requests. State is never stored: it
is re-derived every cycle from labels, pull requests, git refs, and which spec
files exist on the base branch.

## Modules

| Module | Responsibility |
|---|---|
| `paths.py` | Install root vs project root; `Paths` and `find_root`. |
| `github.py` | Every `gh` call. The only place the CLI is invoked. |
| `projects.py` | Projects v2 (GraphQL), isolated so its brittleness cannot spread. |
| `tickets.py` | Naming and issue-text parsing. Pure. |
| `evidence.py` | One snapshot of the world per poll. |
| `projection.py` | Evidence → board column. Pure. |
| `queues.py` | What is eligible, including dependency gating. Pure. |
| `claiming.py` | Atomic cross-machine claims via ref creation. |
| `ledger.py` | This machine's own claims, for self-recovery. |
| `job.py` | Worktree → agent → commit → verify → push → PR. |
| `janitor.py` | Maintenance of work in flight: revisions, conflicts, failures. |
| `reconcile.py` | Writes the board. Never raises. |
| `recovery.py` | Resolves this machine's orphaned claims at startup. |

The pure modules carry the whole state machine, so most behaviour is tested
without touching the network.

## Config keys

`.meeseeks/config.json`:

| Key | Default | Notes |
|---|---|---|
| `owner` | — | Board binding. |
| `repo` | — | Board binding. |
| `project_number` | — | Board binding. |
| `bot_login` | — | Startup fails if `gh api user` disagrees. |
| `reviewer` | — | Gets review requests on every PR. |
| `base_branch` | `main` | Branch point. |
| `remote` | `origin` | Push target. |
| `poll_interval_seconds` | `30` | ≥ 5. About 3 API calls per poll. |
| `max_spec_concurrency` | `1` | Separate, so long impl runs cannot starve the spec queue. |
| `max_impl_concurrency` | `3` | Separate, so long impl runs cannot starve the spec queue. |
| `max_revision_attempts` | `3` | Rounds of review before giving up. |
| `status_field` | `Status` | Project column field name. |
| `columns` | see `config.py` | Column names, merged key-wise over defaults. |
| `labels` | see `config.py` | `arm`, `failed`, `blocked`, merged key-wise. |
| `spec_agent_command` | — | `{prompt_file}` is substituted. |
| `impl_agent_command` | — | `{prompt_file}` is substituted. |
| `verify_command` | — | Gates impl PRs. Runs in the worktree. |

Prompts live in `agents/prompts/` rather than in the config, because prompt
quality is the main lever on output quality and deserves to be diffable.

## Install root vs project root

Shipped files (the daemon, the orchestrator, `prompts/`) are addressed from the
**install root** — where the code is, resolved from `__file__`. Project files
(`.meeseeks/`, `docs/`, `.worktrees/`) are addressed from the **project root** —
where `.meeseeks/config.json` lives, discovered by walking up. `paths.py` is the
only module that resolves either root.

## Claiming

```
POST /repos/{owner}/{repo}/git/refs   → 422 if the ref exists
```

That 422 is a genuine compare-and-swap, so the claim is taken *before* any
agent runs and a loser spends nothing. The claim branch is the work branch.

`git ls-remote --heads origin 'meeseeks/*'` shows every claim held by every
machine in one free call.

## Recovery

At startup, every claim in this machine's ledger is orphaned by definition —
the daemon is the only thing that spawns workers. The only question is whether
the work escaped to the remote:

```
git rev-list --count <remote>/<base>..FETCH_HEAD
```

Non-zero means commits were pushed, so re-running would duplicate landed work;
the ticket is labelled failed for triage. Zero means nothing escaped and the
claim is released for a clean retry.

Note the check is **not** `merge-base --is-ancestor <branch> <base>`. A claim
branch with no commits sits exactly at base and is trivially an ancestor of it,
so that test reports untouched work as landed — the bug that dead-ended the
first plan this system ran.

## Failure and retry

A failed run comments on the issue with the reason, the branch, and the last
60 lines of the log, then applies `meeseeks:failed`. The comment matters: a log
on the machine that failed is invisible to everyone else.

Removing the label retries from scratch — the stale claim and worktree are
discarded first, since a half-finished attempt confuses a cheap model more than
it helps.

## Limitations

- One repo, one project, one base branch.
- Another machine's stale claim needs `release.py`; a daemon will not judge a
  claim it does not own.
- Merged PRs are read from the most recent 100, so dependency gating assumes
  dependencies merged reasonably recently.
