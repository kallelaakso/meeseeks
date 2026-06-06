# Merge-aware dependency handling (pr mode)

Date: 2026-06-06
Status: draft — awaiting review

## Problem

A plan that `depends-on` another can start before the dependency's code is on
`base_branch`. In a two-plan case (B depends-on A) the daemon opens two PRs with
overlapping changes instead of building B on top of a merged A.

### Root cause

The dependency gate assumes **`done/` means "this plan's code is on
`base_branch`"**. That holds for `auto-merge` but is false for `pr` mode:

1. Eligibility gates a plan on its deps being in `done/`
   (`eligible_plans`, `plans.py:58-60`).
2. In `pr` mode a plan moves to `done/` the moment its PR is *opened* — not
   merged. `integrate` → `_open_pr` returns `True` right after `git push` +
   `gh pr create` (`integrate.py:58-70`), and `run_plan` then moves it to
   `done/` (`worker.py:77-79`). **No merge-wait exists.**
3. The dependent's worktree is branched off `base_branch` (`worktree.py:33`),
   which lacks the still-unmerged dependency's changes — so its agent
   re-implements the overlapping work.

`auto-merge` is unaffected: there `done/` genuinely means "merged into
`base_branch`" (`integrate.py:37-55`).

## Goal

In `pr` mode a dependency is satisfied only once its PR is **merged by a human**.
At that point its code is on `base_branch`, so a dependent branching off
`base_branch` correctly builds on it — matching the expected
"open one PR → wait for merge → open the next on top" behavior.

## Design

### New plan states (directories)

State is still "which directory the plan file lives in". Add two:

| dir | meaning |
|---|---|
| `docs/plan/awaiting-merge/` | PR opened, verified; waiting for a human to merge |
| `docs/plan/closed/` | PR was closed without merging (terminal) |

Full `pr`-mode lifecycle:

```
ready-for-work → in-progress → awaiting-merge → done      (PR merged)
                                              → closed     (PR closed unmerged)
                            → failed                       (agent or verify failed)
```

`auto-merge` lifecycle is unchanged (`in-progress → done` / `failed`); it never
uses `awaiting-merge/` or `closed/`.

### Lifecycle changes

**Opening a PR no longer means `done`.** In `run_plan`, when
`integration_mode == "pr"` and the PR was opened successfully, move the plan to
`awaiting-merge/` instead of `done/`. `auto-merge` still moves straight to
`done/`.

**A new merge sweep transitions `awaiting-merge/` plans.** Each daemon poll, for
every plan in `awaiting-merge/`, query its PR state and act:

| PR state | action |
|---|---|
| `MERGED` | move to `done/`, remove worktree |
| `CLOSED` | move to `closed/`, keep worktree + branch (debugging) |
| `OPEN`   | leave in place |

The PR is found by its deterministic branch `plan/<id>` (`worktree.py:27`), so
no extra state needs storing. State query: `gh pr view plan/<id> --json state`
run in the primary repo. `gh` distinguishes `MERGED` from `CLOSED`.

The sweep is a lightweight `gh` query with **no worker process**, so an
`awaiting-merge/` plan does **not** consume a `max_concurrency` slot.

### Eligibility — unchanged

`eligible_plans` still gates on `done/`. Because `done/` now means "merged" in
both modes, the dependency model becomes correct for `pr` mode without touching
the gate.

### Worktree lifecycle

- Keep the worktree while in `awaiting-merge/` (PR is pushed to origin; local
  tree is idle but cheap to keep).
- Remove it on `→ done/` (merged).
- Keep it on `→ closed/`, consistent with `failed/` semantics for debugging.

### Components touched (design level)

- `layout.py` — add `awaiting_merge` and `closed` paths.
- `worker.py` — `pr`-mode success routes to `awaiting-merge/` not `done/`.
- `integrate.py` — no behavior change; `_open_pr` already idempotent on an
  existing open PR.
- new merge-sweep function (likely in `integrate.py` or a small new module) +
  call site in `daemon.poll_once`.
- `docs/plan/awaiting-merge/.gitkeep`, `docs/plan/closed/.gitkeep`.
- `README.md` — document the two new states.

### Crash recovery (bonus)

`awaiting-merge/` survives daemon restarts because state is on disk; the sweep
resumes polling automatically — no live worker to lose (unlike the existing
`in-progress/` limitation).

## Testing approach

- Unit: merge sweep maps `MERGED`/`CLOSED`/`OPEN` → correct directory move,
  with `gh` stubbed.
- Unit: `run_plan` in `pr` mode lands in `awaiting-merge/`; in `auto-merge`
  mode still lands in `done/`.
- Unit: a dependent stays ineligible while its dependency sits in
  `awaiting-merge/`, becomes eligible once it reaches `done/`.

## Unresolved questions

1. `daemon.py` runs the sweep. Should `run_once.py` also run one sweep pass, or
   stay purely "run next eligible plan"?

    -> stay purely "run next eligible plan"

2. `gh pr view` error / PR-not-found (network blip, deleted branch): leave in
   `awaiting-merge/` and log, or move to `failed/` after N retries?

    -> leave and log

3. Sweep cadence: every poll (`poll_interval_seconds`), or throttle PR-state
   queries to avoid `gh` rate limits?

    -> throttle PR-state queries to avoid `gh` rate limits. Add new config option
      `merge_sweep_interval_seconds` and set default to 5 minutes.
