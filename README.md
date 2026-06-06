# Meeseeks – Agentic development environment

A reusable, spec-driven setup for shipping features with AI agents. Two tiers:

- **Planner** — Claude (Opus). Writes specs and plans. Never writes
  implementation code.
- **Implementers** — cheap coding agents (OpenCode / Kimi). Pick up approved
  plans and implement them in isolated git worktrees.

A Python daemon (`agents/`) orchestrates the implementers: claim → run →
verify → integrate.

**NOTE:** This is experimental project for my private use. Please don't expect it to be stable.

## Prerequisites

- Python 3.7+
- Git & Github CLI (`gh`)
- Claude Code subscription
- Open Code subscription

## The workflow

```
request → spec → plan (draft) → ready-for-work → [daemon] → done / failed
          Opus   Opus            you approve       agents
```

1. **Spec** — Opus writes a design doc to `docs/spec/`. You review.
2. **Plan** — on approval, Opus writes an implementation plan to
   `docs/plan/drafts/` (the `write-agent-plan` skill enforces the required
   frontmatter). You approve.
3. **Hand off** — the plan moves to `docs/plan/ready-for-work/`.
4. **Implement** — the daemon claims it, runs an agent in a worktree, runs the
   verify command, integrates, and moves the plan to `done/` (or `failed/`).

Plan state **is** the directory the file lives in — nothing else tracks it.

## Layout

```
CLAUDE.md            workflow rules the planner must follow
agents/              the orchestrator (daemon, worker, worktree, integrate…)
agents/config.json   concurrency, poll cadence, integration mode, agent command
docs/spec/           design docs
docs/plan/
  drafts/            plans being written / reviewed
  ready-for-work/    approved, waiting for an agent
  in-progress/       claimed by a worker
  done/              completed (audit trail; gates depends-on)
  failed/            verify or integration failed (worktree + log kept)
.claude/             enabled plugins (superpowers, frontend-design) + skills
opencode.json        OpenCode permissions for implementer agents
```

## Plan frontmatter

```yaml
---
id: my-feature            # unique, kebab-case
depends-on: [other-id]    # omit or [] if none
---
```

A plan is claimed only once every `depends-on` id has landed in `done/`.

## Running the orchestrator

```bash
python3 agents/run_once.py    # claim + run the next eligible plan (manual)
python3 agents/daemon.py      # poll ready-for-work/ forever, up to max_concurrency
cd agents && python3 -m unittest discover -s tests
```

See [`agents/README.md`](agents/README.md) for config keys and operational
limitations (primary-checkout ownership, crash recovery, failed-state cleanup).

## Using it in a project

This is the environment, not a single project — reuse it wherever you want the
same flow. Copy the repo (or its structure), then:

- Keep `CLAUDE.md` so the planner follows spec → plan → hand-off.
- Point `agents/config.json` `agent_command` / `verify_command` at the target
  project's tooling, and set `integration_mode` (`pr` or `auto-merge`) and
  `base_branch`.
- Drop specs in `docs/spec/`, plans in `docs/plan/`, and start the daemon.

## Contributing

Bug reports and ideas welcome via issues. See the templates under `.github/`.

## License

[MIT](LICENSE) © Kalle Laakso
