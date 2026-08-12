# Meeseeks – Agentic development environment

A spec-driven setup for shipping features with AI agents, driven by GitHub
issues and a project board.

- **Planner** — Claude (Opus), interactive. Brainstorms with you and writes the
  ticket. Never writes specs, plans, or code.
- **Spec agent** — writes the design spec and implementation plan from the
  ticket, opens a `[spec]` PR.
- **Impl agent** — a cheap coding agent (OpenCode / Kimi) that implements the
  merged plan in an isolated worktree and opens a PR.

A Python daemon (`agents/`) runs both, claims work atomically, and keeps the
board in sync.

**NOTE:** This is an experimental project for my private use. Please don't
expect it to be stable.

## Prerequisites

- Python 3.9+
- Git & GitHub CLI (`gh`)
- Claude Code subscription (spec agent), OpenCode subscription (impl agent)
- A GitHub project board and a machine user (see Setup)

## The workflow

```
issue → [meeseeks:spec-me] → [spec] PR → you merge
      → impl PR → you merge → done
```

1. **Ticket** — you and Claude write an issue. Adding the `meeseeks:spec-me`
   label arms it.
2. **Spec** — the daemon writes `docs/spec/<n>-<slug>.md` and
   `docs/plan/<n>-<slug>.md` and opens a `[spec]` PR for review. Request
   changes and the agent revises; merge and implementation is armed.
3. **Implement** — the daemon claims it, runs the agent in a worktree, runs the
   verify command, and opens a PR that closes the issue.
4. **Done** — you merge.

Nothing tracks state separately: it is derived from labels, PRs, git refs, and
which spec files exist on the base branch.

## The board is a projection

The daemon **writes** the Status field and never reads it for decisions:

| Evidence | Column |
|---|---|
| issue closed, or impl PR merged | Done |
| `meeseeks:failed` / `meeseeks:blocked` label | Blocked |
| impl PR open with unaddressed change request | In progress |
| impl PR open | In review |
| impl claim ref exists | In progress |
| `docs/spec/<n>-*.md` on the base branch | Specs (ready for dev) |
| spec PR open | Spec in review |
| otherwise | Backlog |

Dragging a card does nothing — the next poll puts it back. Control the workflow
with labels, reviews, and merges.

## Setup

1. **Board** — create a project with a `Status` field carrying exactly these
   options: `Backlog`, `Spec in review`, `Specs (ready for dev)`,
   `In progress`, `In review`, `Blocked`, `Done`. The daemon refuses to start
   if any are missing and never creates them itself.
2. **Built-in workflows** — keep *auto-add to project* on; turn **off** every
   status-changing workflow and auto-archive, so meeseeks is the only writer.
3. **Machine user** — create a bot account and give it two separate grants:
   repo collaborator (**Write**) and *project* collaborator (**Write**, under
   the project's own Manage access). Repo access does not imply board access.
   This is not optional: GitHub forbids reviewing your own PRs, so a daemon
   running under your token would make its own PRs unreviewable by you.
4. **Token** — a **classic** PAT on the bot with scopes `repo`, `project`, and
   `read:org`. Fine-grained PATs cannot reach a *user-owned* board (their
   Projects permission only covers the token owner's own projects), and
   `read:org` is required even for a user-owned board because `gh project`
   classifies the owner with a query that touches `organization`. Export it as
   `GH_TOKEN` — never put it in `config.json`.
5. **Config** — create `.meeseeks/config.json` at the project root with the
    eight required keys: `owner`, `repo`, `project_number`, `bot_login`,
    `reviewer`, `spec_agent_command`, `impl_agent_command`, `verify_command`.
    `columns`, `labels`, `base_branch`, `remote` and tuning values all default.
6. **Labels** — create `meeseeks:spec-me`, `meeseeks:failed`,
    `meeseeks:blocked`.

## Using it in your own project

Vendor `agents/` (copy, submodule, or subtree). Add `.meeseeks/config.json` with
your eight keys, add the three gitignore lines below, keep a `CLAUDE.md` for
your planner rules, and optionally add `.meeseeks/rules.md` for agent
appendices. Never edit anything under `agents/`.

## Running

```bash
GH_TOKEN=<bot token> python3 agents/daemon.py   # poll, run agents, render board
python3 agents/release.py 42                    # release a stranded claim
cd agents && python3 -m unittest discover -s tests
```

Launch from anywhere by setting `MEESEEKS_ROOT` to the project directory.

## Layout

```
CLAUDE.md              workflow rules the planner must follow
.meeseeks/config.json  board binding, agent commands, verify command
.meeseeks/rules.md     optional project appendix to both prompts
.meeseeks/logs/        per-issue agent logs (gitignored)
.meeseeks/state/       this machine's claims (gitignored)
agents/daemon.py       the daemon
agents/release.py      manual claim release
agents/prompts/        spec.md and impl.md — the agent prompts
agents/orchestrator/   github adapter, evidence, projection, claiming, jobs
docs/spec/             design docs, one per issue
docs/plan/             implementation plans, one per issue
docs/plan/archive/     the retired file-based workflow
```

## How claiming works

Creating a git ref is the only compare-and-swap GitHub offers: the API refuses
to create one that exists. The daemon claims work by creating
`meeseeks/<kind>/<issue>-<slug>` before any agent runs, so a daemon on another
machine that loses the race spends nothing. The lock **is** the work branch.

A daemon releases only its own orphaned claims (recorded in `agents/state/`).
Another machine's stale claim needs `release.py`, deliberately: "stale" and
"slow" are indistinguishable from the outside.

## Contributing

Bug reports and ideas welcome via issues. See the templates under `.github/`.

## License

[MIT](LICENSE) © Kalle Laakso
