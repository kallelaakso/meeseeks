# Agentic development environment — orchestrator

Spec-driven workflow: Claude (Opus) writes specs/plans; cheap implementation
agents (OpenCode/Kimi) pick up approved plans and implement them in isolated git
worktrees.

## Workflow

1. Write a spec to `docs/spec/`, then a plan to `docs/plan/drafts/` (the
   `write-agent-plan` skill enforces the required frontmatter).
2. When happy, move the plan to `docs/plan/ready-for-work/`.
3. The daemon claims it → `in-progress/`, runs the agent in a worktree, verifies,
   then integrates.
   - `auto-merge` mode: merges into `base_branch` and moves the plan to `done/`
   - `pr` mode: opens a PR and moves the plan to `awaiting-merge/`. Once the PR
     is merged it advances to `done/`; if closed unmerged it moves to `closed/`.
   - On failure at any step, the plan lands in `failed/`.

Plan state is **only** the directory the file lives in. Plan frontmatter:

```yaml
---
id: my-feature            # unique, kebab-case
depends-on: [other-id]    # inline list; omit or [] if none
---
```

A plan is only claimed once every `depends-on` id has a file in `done/`.

## Running

```bash
python3 agents/run_once.py      # claim + run the next eligible plan (manual/testing)
python3 agents/daemon.py        # poll ready-for-work/ forever, up to max_concurrency
cd agents && python3 -m unittest discover -s tests    # tests (stdlib only)
```

Configure in `agents/config.json`:

| key | meaning |
|---|---|
| `max_concurrency` | max parallel workers |
| `poll_interval_seconds` | daemon poll cadence |
| `merge_sweep_interval_seconds` | how often to check PR state for awaiting-merge plans (daemon only) |
| `agent_timeout_seconds` | kill a hung agent after N seconds (`0`/unset = no timeout, default 1800) |
| `integration_mode` | `auto-merge` or `pr` |
| `base_branch` | branch agent work integrates into |
| `verify_command` | run in the worktree before integrating; failure → `failed/` |
| `agent_command` | template; placeholders `{plan_path}` `{branch}` `{worktree}` `{verify_command}` |
| `dashboard_port` | HTTP port (default 8787) |
| `dashboard_poll_interval_seconds` | dashboard dir poll cadence (default 3) |
| `dashboard_pr_sweep_interval_seconds` | dashboard PR sweep cadence (default 60) |
| `dashboard_db` | path to dashboard SQLite db (default `agents/dashboard.db`) |

## Dashboard

```bash
python3 agents/dashboard.py   # read-only web UI + background pollers
```

The dashboard binds `127.0.0.1` only and serves a live board at `/`. It is
read-only: the only write is to the `dashboard.db` SQLite file (derived state,
gitignored). The two example plans in `done/` are visible immediately.

## Operational notes / v1 limitations

- **The daemon owns the primary repo checkout.** `auto-merge` checks out
  `base_branch` in the primary repo before merging. Run the daemon against a repo
  whose primary working tree is clean and dedicated to it — don't hand-edit there
  while it runs, or merges/checkouts will fail (the plan then lands in `failed/`).
- **Stranded `in-progress/` plans are recovered at startup.** On daemon (or
  `run_once`) start, any plan left in `in-progress/` is reclaimed: moved back to
  `ready-for-work/`, unless its `plan/<id>` branch was already pushed or merged
  (work landed) — those go to `failed/` for manual triage.
- **Requeue a failed/closed plan** with `python3 agents/requeue.py <plan-id>`.
  It moves the plan from `failed/` or `closed/` back to `ready-for-work/` and
  appends a requeue marker to its log. `done/` plans are never requeueable.
- **`failed/` and `closed/` keep the worktree + branch + `agents/logs/<id>.log`**
  for debugging. Clean up `.worktrees/<id>` yourself after inspecting.
- **A dependency is satisfied only once its PR is merged.** `eligible_plans`
  looks at `done/` (not `awaiting-merge/`), so a dependent plan won't start until
  the dependency's PR is actually merged.
- **Filename collisions overwrite.** Re-using a plan filename that already exists
  in `done/`/`failed/`/`closed/` overwrites the prior file. Keep plan filenames
  unique.
- **`done/` is kept forever** (audit trail); `eligible_plans` re-parses it each
  poll — fine at modest scale.
