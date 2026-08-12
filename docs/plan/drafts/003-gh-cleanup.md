---
id: gh-cleanup
depends-on: [gh-daemon]
spec: 2026-08-12-github-board-workflow-design.md
---

# Plan 3 — Delete the file-based system, promote the board daemon

## Goal

Remove the old file-based state machine and the dashboard, rename the `board_*`
artifacts to canonical names, and rewrite the docs so the repo describes the
workflow it now has.

## Critical constraints — read before starting

**The old daemon is executing this plan while you delete it.** That is safe:
Python has already imported the modules it needs, so removing the files does not
affect the running process. But:

- **Do not delete or move anything under `docs/plan/` except adding files.** The
  running daemon still needs `ready-for-work/`, `in-progress/`, and `done/` to
  file this very plan when the agent finishes. Archiving those directories is a
  manual step the human performs afterward.
- **Do not touch `docs/plan/drafts/`, `ready-for-work/`, `in-progress/`,
  `awaiting-merge/`, `done/`, `closed/`, `failed/`.**
- Do not attempt to start or restart any daemon.

## Verify

```
cd agents && python3 -m unittest discover -s tests
```

Must pass with the deleted modules' tests removed.

---

## Step 1 — Delete the dashboard

```
agents/dashboard.py
agents/dashboard/           (whole package, including static/)
agents/tests/test_server.py
agents/tests/test_model.py
agents/tests/test_poller.py
agents/tests/test_ledger.py
agents/tests/test_gh.py
```

Also delete any `agents/dashboard.db` and remove `dashboard.db` from
`.gitignore` if listed there.

The board is the dashboard now. The transition timeline it provided is
recoverable later from GitHub's event API without a local poller, so nothing is
permanently lost.

## Step 2 — Delete the file-based state machine

```
agents/orchestrator/plans.py          agents/tests/test_plans.py
agents/orchestrator/layout.py
agents/orchestrator/merge.py          agents/tests/test_merge.py
agents/orchestrator/requeue.py        agents/tests/test_requeue.py
agents/orchestrator/claim.py          agents/tests/test_claim.py
agents/orchestrator/recovery.py       agents/tests/test_recovery.py
agents/orchestrator/integrate.py      agents/tests/test_integrate.py
agents/orchestrator/worker.py         agents/tests/test_worker.py
agents/orchestrator/config.py         agents/tests/test_config.py
agents/daemon.py
agents/run_once.py                    agents/tests/test_run_once.py
agents/requeue.py
agents/config.json
```

Before deleting `integrate.py` and `worker.py`, confirm nothing from plan 2
imports them — `job.py` should own the push/PR path entirely. If anything does
still import them, port the needed function into `job.py` first rather than
keeping the module alive.

`worktree.py` and `fsops.py` **survive**. Remove the now-unused
`create_worktree` (the branch-creating variant) and `sync_base` from
`worktree.py` if nothing references them, keeping `create_worktree_on`,
`fetch_base`, and `remove_worktree`. `branch_name()` (the old `plan/<slug>`
helper) goes — `tickets.branch()` replaces it.

## Step 3 — Promote `board_*` to canonical names

```
agents/board_daemon.py                -> agents/daemon.py
agents/board.json                     -> agents/config.json
agents/orchestrator/boardconfig.py    -> agents/orchestrator/config.py
agents/tests/test_boardconfig.py      -> agents/tests/test_config.py
```

Use `git mv` so history follows. Update every import accordingly. After this
step `grep -rn 'board_' agents/` must return nothing.

Keep `agents/state/` (the claim ledger) and add `agents/state/` to `.gitignore`
— claims are machine-local and must never be committed. Same for
`agents/logs/`, if not already ignored.

## Step 4 — Rewrite `README.md`

Replace the workflow, layout, and running sections. The new content:

- The flow: `issue → [label] → spec PR → merge → impl PR → merge → done`, with
  the human writing the ticket, reviewing two PRs, and merging.
- The board is a **projection**: dragging a card does nothing; control is via
  labels, PR merges, and reviews.
- Prerequisites gain: a GitHub project with the seven Status options, a machine
  user, and `GH_TOKEN` in the environment.
- Setup: create the bot account, add it as a collaborator, issue a fine-grained
  PAT (Contents RW, Pull requests RW, Issues RW, Projects RW), add the columns,
  disable status-changing built-in project workflows, keep auto-add on.
- Running: `GH_TOKEN=… python3 agents/daemon.py`, plus
  `python3 agents/release.py <issue>`.
- Delete the plan-frontmatter section and the directory-state table entirely.

## Step 5 — Rewrite `CLAUDE.md`

The planner's role changes. New content:

1. Brainstorm and grill the human before anything else.
2. Write the ticket body (Problem / Goals / Non-goals / Constraints /
   Acceptance criteria / optional `Depends on: #N`), get approval, then
   `gh issue create`.
3. Add the `meeseeks:spec-me` label only on the human's explicit go.
4. Never write specs, plans, or implementation code — those belong to the
   daemons.

Keep the hard-rule framing of the current file; only the scope moves up one
level. Document the ticket-body convention here, since it is the sole input to
an autonomous spec run and nothing downstream can rescue a poor ticket.

## Step 6 — Retire `write-agent-plan`

Delete `.claude/skills/write-agent-plan/`. Its content now lives in
`agents/prompts/spec.md`, which is what actually writes plans.

Update `.claude/settings.json` only if it references the skill by name.

## Step 7 — Update `agents/README.md`

Rewrite around the new model: config keys, the claim protocol (create-ref 422),
the ledger, recovery semantics, and the failure/re-arm loop. Delete the
"primary-checkout ownership" and "integration modes" sections — with
`auto-merge` gone, neither hazard exists.

## Acceptance criteria

- Tests pass; the suite contains no reference to plans, layout, dashboard, or
  integration modes.
- `grep -rn 'ready-for-work\|awaiting-merge\|depends-on:\|integration_mode' agents/ README.md CLAUDE.md`
  returns nothing.
- `grep -rn 'board_' agents/` returns nothing.
- `docs/plan/` is untouched apart from this plan file's own movement by the
  daemon.

## Manual steps for the human, after this PR merges

The agent must not do these — they would break the machinery mid-flight.

1. Stop the old daemon. Do not restart it; its files are gone.
2. `mkdir -p docs/plan/archive && git mv docs/plan/{drafts,ready-for-work,in-progress,awaiting-merge,done,closed,failed} docs/plan/archive/`
   (whichever exist), then commit.
3. Create the bot account and PAT; export `GH_TOKEN`.
4. Add the `Spec in review` and `Blocked` columns; disable status-changing
   built-in project workflows; leave auto-add enabled.
5. Start `python3 agents/daemon.py` and file the first real ticket.
