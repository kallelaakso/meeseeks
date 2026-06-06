---
name: write-agent-plan
description: Use when writing an implementation plan that OpenCode/Kimi agents will pick up from docs/plan/ready-for-work. Enforces the required frontmatter (id, depends-on) and placement so the orchestrator can parse and schedule it.
---

# Writing an agent-consumable plan

Plans implemented by the autonomous agents MUST start with this frontmatter:

```yaml
---
id: <unique-kebab-slug>
depends-on: [other-id, another-id]   # omit or use [] if none
spec: <filename.md>                  # optional, links plan to its design spec
---
```

Rules:
- `id` is required, unique across all plans, kebab-case.
- `depends-on` is an **inline** list only: `[a, b]`. Block lists are not supported.
- Each id in `depends-on` must match the `id` of another plan. An agent only
  claims this plan once every dependency's file is in `docs/plan/done/`.
- `spec` is optional. When present it names a file in `docs/spec/` and links
  the plan to its design spec for dashboard rollup. One spec may be referenced
  by many plans.
- The body after the second `---` is the implementation plan markdown the agent
  reads and executes.

Workflow / placement:
1. Write the plan to `docs/plan/drafts/<NNN>-<slug>.md` while iterating with the human.
2. When the human approves, move it to `docs/plan/ready-for-work/`.
3. Do not place a plan in `ready-for-work/` until its dependencies exist as
   plans (their ids are known) — otherwise it can never become eligible.

Keep one plan = one independently-mergeable vertical slice. If two pieces must
land together, they are one plan; if one must precede another, use `depends-on`.
