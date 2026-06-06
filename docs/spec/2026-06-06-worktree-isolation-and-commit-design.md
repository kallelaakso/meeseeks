# Worktree isolation + orchestrator-owned commits

Date: 2026-06-06
Status: draft — awaiting review

## Problem

An agent run "succeeded" (exit 0, all tests passing) but integration failed with
`gh pr create … could not find any commits between origin/main and
plan/<id>`, and the plan was filed to `failed/`. The implemented work was
intact but **uncommitted in the main repo checkout** — the agent had edited the
primary working tree instead of its isolated worktree, so the plan branch was
empty.

### Root cause

Two independent harness defects:

1. **The agent escapes its worktree.** `worker.run_plan` claims the plan into
   the *main repo's* `docs/plan/in-progress/`, then invokes the agent with
   `plan_path = claimed.resolve()` — an absolute path pointing into the main
   repo. The coding agent (OpenCode/Kimi) anchors its "project root" to the
   plan file's location, so it edits the main checkout and ignores its `cwd`
   worktree. The worktree stays empty; the branch gets no commits. Relative
   paths in the plan body (`agents/orchestrator/fsops.py`, …) resolve against
   the main repo, compounding it.

2. **Nothing guarantees a commit.** Integration (`_open_pr` / `_auto_merge`)
   needs commits on the branch, but the orchestrator never commits and the
   `agent_command` prompt never tells the agent to. When the agent leaves
   changes uncommitted (or edits elsewhere), `git push` pushes an empty branch
   and `gh pr create` fails with a cryptic error. The existing `test_worker`
   tests masked this — their fake agents run `git add -A && git commit`
   explicitly, an assumption the real prompt does not enforce.

## Goal

- An agent's file edits reliably land **inside its worktree**, on its branch.
- The orchestrator **guarantees a commit** exists before integrating, and fails
  fast with a clear message when the agent produced no changes — instead of
  surfacing a confusing `gh` error.

## Design

### Fix 1 — give the agent a worktree-local plan, anchor it there

After creating the worktree, copy the claimed plan into the worktree (e.g.
`<worktree>/PLAN.md`) and register that filename in the worktree's
`.git/info/exclude` so it can never be committed. Format `agent_command` with
`plan_path` = the **worktree-local** plan path, and keep `cwd = worktree`.

The agent now opens a plan that lives inside the worktree, so its project root
resolves to the worktree and edits land on the branch. The local exclude keeps
the plan copy out of `git add -A`.

The `agent_command` prompt should also state that all plan paths are relative to
the worktree and edits must stay within it — defense in depth, not the primary
mechanism.

### Fix 2 — orchestrator owns the commit, and verifies one exists

After the agent exits 0, in the worktree:

1. `git add -A` and, if anything is staged, commit it with a generated message
   (e.g. `implement <plan-id>`). This handles agents that leave changes
   uncommitted.
2. Require commits ahead of `base_branch` (`git rev-list <base>..HEAD`). If
   there are none, **fail** with a clear log line (`agent produced no commits —
   nothing to integrate`) and move the plan to `failed/`.

This supports all three agent behaviors: commits itself (step 1 is a no-op,
step 2 passes), leaves changes dirty (step 1 commits), or does nothing / edits
outside the worktree (step 2 fails fast with a useful message). It removes the
reliance on the agent committing, so the `agent_command` prompt no longer needs
to mention committing.

### Components touched (design level)

- `worker.py` — copy plan into worktree + local-exclude it; commit-and-verify
  step between the agent run and `integrate`.
- `worktree.py` — likely a small helper to write `.git/info/exclude`.
- `config.json` / `agent_command` — point `plan_path` at the worktree copy;
  tighten the prompt wording.
- Integration code unchanged (it just now always has commits to work with).

## Testing approach

- Unit: an agent that edits files but does **not** commit → orchestrator commits
  them, branch ends with one commit, plan → `awaiting-merge/` (pr) / `done/`
  (auto-merge).
- Unit: an agent that commits itself → still succeeds (no double-commit
  failure).
- Unit: an agent that produces **no** changes in the worktree → plan → `failed/`
  with the "no commits" log line (this is the regression test for the bug).
- Unit: the worktree-local plan copy is excluded — `git add -A` never stages it.

## Unresolved questions

1. Commit message for orchestrator-made commits: just `implement <plan-id>`, or
   richer (include plan title / verify result)?
2. Should the plan file itself be committed onto the branch (audit trail in the
   PR), or stay purely orchestrator state outside git (current behavior)?
3. Worktree-local plan path: fixed name (`PLAN.md`) at the worktree root, or
   mirror its `docs/plan/...` path inside the worktree?
