# Project instructions

## The workflow — ALWAYS follow this

This project uses **spec-driven development**. You (Claude) do NOT implement
features. Coding agents do. Your job is spec → plan, then hand off.

Whenever I ask for anything that changes behavior — even phrased as
"let's implement X", "add X", "fix X", "build X" — interpret it as a request
to start this workflow, NOT to write implementation code:

1. **Pull** — run `git pull` before starting any work.
2. **Spec** — write a design doc to `docs/spec/`. Wait for my review.
3. **Plan** — after I approve the spec, write a detailed implementation plan
   to `docs/plan/drafts/`. Wait for my approval.
4. **Hand off** — when I approve the plan, move it to
   `docs/plan/ready-for-work/`. Coding agents watch that folder and do the
   implementation.

## Hard rules

- NEVER write implementation code, edit source files, or run the
  implementation yourself. If you catch yourself about to edit a non-doc file
  to build a feature, STOP — you've skipped the workflow.
- NEVER skip a step. Spec before plan, plan before hand-off, my review at each
  gate.
- The ONLY things you write are spec docs and plan docs. Everything else is
  the coding agents' job.
- If a request is ambiguous about which step we're on, ask me — don't assume
  and start coding.

## Paths

- Specs: `docs/spec/YYYY-MM-DD-<topic>-design.md`
- Plan drafts: `docs/plan/drafts/YYYY-MM-DD-<feature-name>.md`
- Approved plans (handed to agents): `docs/plan/ready-for-work/`

These override the default superpowers locations (`docs/superpowers/specs/`,
`docs/superpowers/plans/`) and any path given by the brainstorming,
writing-plans, subagent-driven-development, or requesting-code-review skills.

Do not use git worktrees for plan work — write directly in `docs/plan/drafts/`.

## Plan format

End every plan with a short list of unresolved questions for me to answer, if
any. Keep them extremely concise.
