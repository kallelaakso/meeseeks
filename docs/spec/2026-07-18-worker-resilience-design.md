# Worker resilience — timeout, crash recovery, requeue

Date: 2026-07-18
Status: draft — awaiting review

## Problem

The orchestrator's failure handling has three gaps that each require manual
`mv` intervention or leave a worker permanently stuck:

1. **No agent timeout.** `worker._run_agent` runs the implementer via
   `subprocess.run` with no timeout. A hung agent (model stall, wedged network,
   runaway loop) holds a `max_concurrency` slot forever; the daemon cannot
   reclaim it without a human killing the process.
2. **No crash recovery for `in-progress/`.** The daemon tracks live workers only
   in an in-memory `running` dict. If a worker process is killed between claim
   and finish, its plan is stranded in `in-progress/` — no process owns it and
   nothing ever moves it. Recovery today is a manual `mv` back to
   `ready-for-work/`.
3. **No retry path for `failed/` (or `closed/`).** A plan that failed verify or
   integration, or a PR closed unmerged, is terminal. Re-running it means a
   human manually moving the file back and remembering to clear stale worktree
   state.

## Goal

- A hung agent is killed after a configurable timeout and its plan fails
  cleanly, freeing the slot.
- A daemon restart automatically reclaims plans stranded in `in-progress/`,
  without silently re-running work that already partially landed.
- Requeuing a `failed/`/`closed/` plan is a single first-class operation, usable
  from a CLI now and from the dashboard later (Spec B), that both a human and
  the UI call.

## Non-goals

- Automatic retry/backoff. Retry is always an explicit human (or UI) action —
  auto-retrying a genuinely broken plan just burns cycles. A timeout lands in
  `failed/` like any other failure; a human decides whether to requeue.
- Dashboard buttons. This spec defines the core `requeue()` operation; the UI
  surface is Spec B.
- A new `timed-out/` state. A timeout is a failure and reuses `failed/`.

## Design

### 1. Agent timeout

New config key `agent_timeout_seconds`:

- Optional. **Default `1800`** (30 min). `0` or omitted means *no timeout*, so
  existing `config.json` files keep working unchanged.
- Validated in `config.py`: if present, must be `>= 0`.

`worker._run_agent` passes `timeout=` to `subprocess.run` (omit / pass `None`
when the value is `0`). On `subprocess.TimeoutExpired`:

- Kill the agent's process group (the agent is launched with `shell=True` and
  may spawn children; kill the whole group, not just the shell). Launch it in a
  new session (`start_new_session=True`) so the group is killable via
  `os.killpg`.
- Log `agent timed out after Ns — killed`.
- Return failure. `run_plan`'s existing failure path takes over: plan → `failed/`,
  worktree + branch + log kept for debugging. No new state, no new branch in
  control flow.

### 2. Crash recovery on daemon startup

Because the daemon owns the primary checkout and is the sole writer (existing
README invariant), any plan sitting in `in-progress/` at daemon **start** is by
definition orphaned — no live worker owns it.

New module `orchestrator/recovery.py`:

```
recover_stranded(layout, config, *, git=<default runner>) -> list[str]
```

Returns the list of recovered plan ids (for logging and testability). For each
plan in `in-progress/`:

- **Partial-landing guard.** If `plan/<id>`'s work has already escaped the
  worker — the branch is pushed to the remote (`git ls-remote --heads <remote>
  plan/<id>` is non-empty) **or** its commits are already an ancestor of
  `base_branch` (merged) — move the plan to `failed/` and log
  `interrupted after work landed; triage manually`. This avoids silently
  re-running a plan that had already pushed a PR or merged just before the
  crash.
- **Otherwise** move the plan back to `ready-for-work/` and log
  `recovered stranded in-progress plan`. The next poll re-claims it; its stale
  worktree/branch is force-recreated by the existing `create_worktree`.

The git runner is injectable so tests can drive the guard both ways without a
real remote.

Wiring:

- `daemon.main()` calls `recover_stranded` **once**, before the poll loop.
- `run_once.py` (manual/single-shot) also calls it at start — cheap, same guard,
  keeps the two entrypoints consistent.

### 3. Explicit requeue

New module `orchestrator/requeue.py`:

```
requeue(plan_id, layout) -> Path
```

- Looks for `<plan_id>`'s file in `failed/`, then `closed/`. (Match by parsed
  plan `id`, not filename, to be robust to filename/​id drift.)
- Moves it into `ready-for-work/` and returns the new path.
- **Never** touches `done/` (audit trail + dependency gate) — raises if the id
  is only there or nowhere.
- Appends `requeued at <iso>` to `agents/logs/<id>.log`, so one log accumulates
  the full attempt history rather than being wiped per attempt.
- Leaves the old worktree in place; `create_worktree` force-cleans it on the
  next run.

Thin CLI wrapper `agents/requeue.py <plan-id>` for humans. Spec B's dashboard
button will call the same `requeue()` core — no logic duplicated in the UI.

## Error handling

- Timeout: caught as `TimeoutExpired`, converted to a normal agent failure. Any
  `os.killpg` error (process already gone) is swallowed.
- Recovery: `recover_stranded` never raises out of `main()` — a git probe error
  for one plan is logged and that plan is left in `in-progress/` for the next
  restart, rather than aborting the daemon.
- Requeue: raises `ValueError` (surfaced by the CLI as a non-zero exit + message)
  when the id isn't in `failed/`/`closed/`.

## Testing

Stdlib `unittest`, reusing `tests/helpers.py` fixtures:

- **Timeout** — fake agent command that sleeps past a tiny `agent_timeout_seconds`;
  assert plan lands in `failed/`, log records the timeout, slot is released.
  Assert `agent_timeout_seconds` omitted / `0` runs with no timeout.
- **Config** — `agent_timeout_seconds` negative → `ValueError`; absent → default
  `1800`; `0` accepted.
- **Recovery** — stranded plan with no landed branch → `ready-for-work/`; with a
  pushed/merged branch (injected git runner) → `failed/`; returns correct id
  list; a probe error leaves the plan in place and doesn't raise.
- **Requeue** — from `failed/` → `ready-for-work/`; from `closed/` →
  `ready-for-work/`; `done/`-only id rejected; unknown id rejected; log line
  appended.

## Modules

- **Edit:** `orchestrator/worker.py` (timeout + process group), `orchestrator/config.py`
  (new key + validation), `daemon.py` and `run_once.py` (call recovery),
  `README.md` + `agents/README.md` (config key + updated limitations).
- **Add:** `orchestrator/recovery.py`, `orchestrator/requeue.py`,
  `agents/requeue.py`, and matching `tests/test_recovery.py`,
  `tests/test_requeue.py`, plus timeout cases in `tests/test_worker.py` /
  `tests/test_config.py`.

## Unresolved questions

None outstanding — timeout default (`1800`/nullable) and the partial-landing
recovery guard were both confirmed during design.
