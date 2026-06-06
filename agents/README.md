# Agentic development environment — orchestrator

Spec-driven workflow: Claude (Opus) writes specs/plans; cheap implementation
agents (OpenCode/Kimi) pick up approved plans and implement them in isolated git
worktrees.

## Workflow

1. Write a spec to `docs/spec/`, then a plan to `docs/plan/drafts/` (the
   `write-agent-plan` skill enforces the required frontmatter).
2. When happy, move the plan to `docs/plan/ready-for-work/`.
3. The daemon claims it → `in-progress/`, runs the agent in a worktree, verifies,
   integrates, then moves it to `done/` (or `failed/`).

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
| `integration_mode` | `auto-merge` or `pr` |
| `base_branch` | branch agent work integrates into |
| `verify_command` | run in the worktree before integrating; failure → `failed/` |
| `agent_command` | template; placeholders `{plan_path}` `{branch}` `{worktree}` `{verify_command}` |

## Operational notes / v1 limitations

- **The daemon owns the primary repo checkout.** `auto-merge` checks out
  `base_branch` in the primary repo before merging. Run the daemon against a repo
  whose primary working tree is clean and dedicated to it — don't hand-edit there
  while it runs, or merges/checkouts will fail (the plan then lands in `failed/`).
- **No crash recovery for `in-progress/`.** If a worker process is killed between
  claiming and finishing, its plan is stranded in `in-progress/`. Recover
  manually: inspect, then move it back to `ready-for-work/`.
- **`failed/` keeps the worktree + branch + `agents/logs/<id>.log`** for
  debugging. Clean up `.worktrees/<id>` yourself after inspecting.
- **Filename collisions overwrite.** Re-using a plan filename that already exists
  in `done/`/`failed/` overwrites the prior file. Keep plan filenames unique.
- **`done/` is kept forever** (audit trail); `eligible_plans` re-parses it each
  poll — fine at modest scale.
